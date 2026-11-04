"""A bounded local Pi RPC worker, with persistent per-job sessions."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from me3.harnesses import PiBackend, _drain, _reap


class PersistentPiBackend(PiBackend):
    def __init__(
        self, command, *, model: str, provider: str, **options
    ) -> None:
        super().__init__(command, **options)
        if not model or not provider:
            raise ValueError("Exact worker model and provider are required")
        self.model, self.provider = model, provider
        self.process = None
        self.job_root: Path | None = None
        self.diagnostics: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    def _environment(self) -> dict[str, str]:
        # Do not pass speech/foreground credentials to delegated inference.
        names = (
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "NO_PROXY",
            "PI_CODING_AGENT_DIR",
        )
        return {
            **{name: os.environ[name] for name in names if name in os.environ},
            **self.env,
        }

    async def _ensure_process(self, workspace: Path) -> None:
        job_root = workspace.resolve().parent
        if (
            self.process is not None
            and self.process.returncode is None
            and job_root == self.job_root
        ):
            return
        await self._close_process()
        workspace.mkdir(parents=True, exist_ok=True)
        session_dir = job_root / ".pi"
        session_dir.mkdir(mode=0o700, exist_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            "--session",
            str(session_dir / "session.jsonl"),
            cwd=workspace,
            env=self._environment(),
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self.max_bytes,
        )
        self.job_root = job_root
        self.diagnostics = asyncio.create_task(_drain(self.process.stderr))

    async def _send(self, record: dict) -> None:
        self.process.stdin.write(json.dumps(record).encode() + b"\n")
        await self.process.stdin.drain()

    async def _state(self) -> None:
        request_id = uuid.uuid4().hex
        await self._send({"type": "get_state", "id": request_id})
        total = 0
        while line := await self.process.stdout.readline():
            total += len(line)
            if total > self.max_bytes:
                raise ValueError("Pi state output exceeds limit")
            record = json.loads(line)
            if (
                record.get("type") != "response"
                or record.get("id") != request_id
            ):
                continue
            if not record.get("success"):
                raise RuntimeError("Pi state request failed")
            state = record.get("data", {})
            model = state.get("model") or {}
            if (
                model.get("id") != self.model
                or model.get("provider") != self.provider
            ):
                raise ValueError(
                    "Pi worker model/provider differs from selection"
                )
            if state.get("isStreaming"):
                raise RuntimeError("Pi has unsettled prior work")
            return
        raise RuntimeError("Pi exited before model verification")

    async def _turn(self, prompt: str) -> str:
        turn_id, result_id = uuid.uuid4().hex, uuid.uuid4().hex
        await self._send({"id": turn_id, "type": "prompt", "message": prompt})
        accepted = ended = requested = False
        total = 0
        while line := await self.process.stdout.readline():
            total += len(line)
            if total > self.max_bytes:
                raise ValueError("Pi output exceeds limit")
            record = json.loads(line)
            kind = record.get("type")
            if kind == "message_end":
                message = record.get("message", {})
                if message.get("role") == "assistant":
                    if message.get("stopReason") in {"error", "aborted"}:
                        raise RuntimeError(
                            "Pi inference failed or was aborted"
                        )
                    ended = True
            elif kind == "tool_execution_start":
                raise RuntimeError("Worker attempted a disabled tool")
            elif kind == "response":
                if not record.get("success"):
                    raise RuntimeError("Pi rejected a protocol command")
                if record.get("id") == turn_id:
                    if record.get("data", {}).get("disposition") == "handled":
                        raise RuntimeError("Pi did not start a model run")
                    accepted = True
                elif record.get("id") == result_id and requested:
                    text = record.get("data", {}).get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("Pi returned no usable text")
                    return text
            elif (
                kind == "agent_settled"
                and accepted
                and ended
                and not requested
            ):
                requested = True
                await self._send(
                    {"id": result_id, "type": "get_last_assistant_text"}
                )
        raise RuntimeError("Pi exited before a settled result")

    async def run(
        self,
        prompt: str,
        workspace: Path,
        *,
        foreground: bool = False,
    ) -> str:
        if foreground:
            raise ValueError(
                "Pi worker cannot substitute for foreground inference"
            )
        if not prompt.strip() or len(prompt) > 100_000:
            raise ValueError("Invalid worker prompt")
        async with self.lock:
            try:
                async with asyncio.timeout(self.timeout):
                    await self._ensure_process(workspace)
                    await self._state()
                    return await self._turn(prompt)
            except BaseException:
                await self._close_process()
                raise

    async def _close_process(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        process.stdin.close()
        drain = asyncio.create_task(_drain(process.stdout))
        await _reap(process)
        await asyncio.gather(drain, self.diagnostics)
        self.diagnostics = None
        self.job_root = None

    async def close(self) -> None:
        async with self.lock:
            await self._close_process()
