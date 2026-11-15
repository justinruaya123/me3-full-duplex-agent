"""Explicit Pi foreground profile: warm, tool-free, reasoning-off RPC."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import uuid

from me3.harnesses import _drain
from me3.pi_worker import PersistentPiBackend


class PiForegroundBackend(PersistentPiBackend):
    """Separate from workers; host supplies all confirmed dialogue context."""

    def __init__(self, *args, on_stage=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_stage = on_stage
        self.directory = None
        self.read_bytes = 0

    async def _start(self):
        if self.process is not None and self.process.returncode is None:
            return
        await self._close_process()
        self.directory = tempfile.TemporaryDirectory(prefix="me3-foreground-")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command, "--no-session", "--thinking", "off",
                cwd=self.directory.name, env=self._environment(),
                start_new_session=True,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.max_bytes,
            )
            self.diagnostics = asyncio.create_task(_drain(self.process.stderr))
        except BaseException:
            self.directory.cleanup()
            self.directory = None
            raise

    async def _record(self):
        line = await self.process.stdout.readline()
        if not line:
            raise RuntimeError("Pi foreground exited before settlement")
        self.read_bytes += len(line)
        if self.read_bytes > self.max_bytes:
            raise ValueError("Pi foreground output exceeds limit")
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError("Invalid Pi foreground record")
        return record

    async def _request(self, kind, **fields):
        request_id = uuid.uuid4().hex
        await self._send({"type": kind, "id": request_id, **fields})
        while True:
            record = await self._record()
            if record.get("type") == "response":
                if not record.get("success"):
                    raise RuntimeError("Pi foreground rejected a command")
                if record.get("id") == request_id:
                    return record.get("data") or {}

    async def _prepare(self):
        self.read_bytes = 0
        await self._start()
        # Never let undelivered output or another owner's context survive.
        data = await self._request("new_session")
        if data.get("cancelled"):
            raise RuntimeError("Pi foreground context reset rejected")
        levels = await self._request("get_available_thinking_levels")
        if "off" not in levels.get("levels", []):
            raise ValueError("Pi foreground model cannot disable reasoning")
        await self._request("set_thinking_level", level="off")
        await self._request("set_auto_retry", enabled=False)
        state = await self._request("get_state")
        model = state.get("model") or {}
        if (model.get("id"), model.get("provider")) != (
            self.model, self.provider
        ):
            raise ValueError("Pi foreground model/provider changed")
        if state.get("thinkingLevel") != "off":
            raise ValueError("Pi foreground reasoning is not off")
        if state.get("isStreaming") or state.get("isCompacting"):
            raise RuntimeError("Pi foreground has unsettled work")

    async def stream(self, prompt):
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > 100_000
        ):
            raise ValueError("Invalid foreground prompt")
        async with self.lock:
            settled = False
            try:
                async with asyncio.timeout(self.timeout):
                    await self._prepare()
                    if self.on_stage:
                        self.on_stage(
                            "llm_request", chars=len(prompt), messages=1
                        )
                    turn_id = uuid.uuid4().hex
                    await self._send({"type": "prompt", "id": turn_id,
                                      "message": prompt})
                    accepted = ended = False
                    text = ""
                    while True:
                        record = await self._record()
                        kind = record.get("type")
                        if kind == "response":
                            if not record.get("success"):
                                error = str(record.get("error", ""))
                                if "No API key" in error:
                                    raise RuntimeError(
                                        "Pi foreground has no credentials; "
                                        "sign in using scripts/me3.sh pi"
                                    )
                                raise RuntimeError(
                                    "Pi foreground prompt rejected"
                                )
                            if record.get("id") == turn_id:
                                data = record.get("data", {})
                                if data.get("disposition") != "started":
                                    raise RuntimeError(
                                        "Pi foreground did not start"
                                    )
                                accepted = True
                        elif kind == "message_update":
                            event = record.get("assistantMessageEvent", {})
                            event_type = event.get("type", "")
                            if event_type.startswith(
                                ("thinking_", "toolcall_")
                            ):
                                raise ValueError(
                                    "Pi foreground reasoning/tools disabled"
                                )
                            if event_type == "text_delta":
                                delta = event.get("delta")
                                if not isinstance(delta, str):
                                    raise ValueError("Invalid foreground text")
                                if len(text) + len(delta) > 16000:
                                    raise ValueError(
                                        "Foreground output exceeds limit"
                                    )
                                if delta and not text and self.on_stage:
                                    self.on_stage("llm_first_token")
                                text += delta
                                if delta:
                                    yield delta
                        elif kind == "message_end":
                            message = record.get("message", {})
                            if message.get("role") != "assistant":
                                continue
                            reason = message.get("stopReason")
                            if reason not in {"stop", "length"}:
                                raise RuntimeError(
                                    "Pi foreground inference failed"
                                )
                            identity = (
                                message.get("model"), message.get("provider")
                            )
                            if identity != (self.model, self.provider):
                                raise ValueError(
                                    "Pi foreground response model changed"
                                )
                            content = message.get("content", [])
                            if any(
                                block.get("type") != "text"
                                for block in content
                            ):
                                raise ValueError(
                                    "Pi foreground reasoning/tools disabled"
                                )
                            final = "".join(
                                block.get("text", "") for block in content
                            )
                            if final != text or not text.strip():
                                raise ValueError(
                                    "Pi foreground final text mismatch/empty"
                                )
                            ended = True
                        elif kind == "agent_settled":
                            if (
                                not accepted or not ended
                                or record.get("aborted")
                            ):
                                raise RuntimeError(
                                    "Pi foreground did not complete"
                                )
                            settled = True
                            return
                        elif kind in {
                            "tool_execution_start", "auto_retry_start"
                        }:
                            raise RuntimeError(
                                "Pi foreground unexpected tool/retry"
                            )
            finally:
                if not settled:
                    # Cancellation of foreground must not touch any worker.
                    await self._close_process()

    async def run(self, prompt, workspace: Path, *, foreground=False):
        return "".join([text async for text in self.stream(prompt)])

    async def _close_process(self):
        try:
            await super()._close_process()
        finally:
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None
