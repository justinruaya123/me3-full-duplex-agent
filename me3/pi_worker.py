"""A bounded local Pi RPC worker, with one context and journal per job revision."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

from me3.configuration import OPENROUTER_BASE_URL, pinned_route
from me3.harnesses import PiBackend, _drain, _reap


class PersistentPiBackend(PiBackend):
    def __init__(
        self, command, *, model: str, provider: str, routing_provider="",
        serving_name="", **options
    ) -> None:
        super().__init__(command, **options)
        if not model or not provider:
            raise ValueError("Exact worker model and provider are required")
        self.model, self.provider = model, provider
        self.routing_provider, self.serving_name = routing_provider, serving_name
        self.process = None
        self.revision_dir: Path | None = None
        self.diagnostics: asyncio.Task | None = None
        self.on_text_delta = None
        self.lock = asyncio.Lock()
        self.agent_directory = None
        self.verified_provider = None

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
        revision_dir = workspace.resolve()
        if (
            self.process is not None
            and self.process.returncode is None
            and revision_dir == self.revision_dir
        ):
            return
        await self._close_process()
        workspace.mkdir(parents=True, exist_ok=True)
        session_dir = revision_dir / ".pi"
        session_dir.mkdir(mode=0o700, exist_ok=True)
        env = self._environment()
        if self.provider == "openrouter":
            # An isolated config never changes the historical Pi login/catalog.
            self.agent_directory = tempfile.TemporaryDirectory(prefix="me3-pi-")
            directory = Path(self.agent_directory.name)
            env["PI_CODING_AGENT_DIR"] = str(directory)
            override = {"compat": {
                "thinkingFormat": "openrouter",
                "openRouterRouting": pinned_route(self.routing_provider),
            }}
            models = {"providers": {"openrouter": {
                "baseUrl": OPENROUTER_BASE_URL,
                "modelOverrides": {self.model: override},
            }}}
            (directory / "models.json").write_text(json.dumps(models))
            (directory / "settings.json").write_text(json.dumps({
                "retry": {"enabled": False, "provider": {"maxRetries": 0}},
                "compaction": {"enabled": False},
                "enableInstallTelemetry": False,
            }))
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            "--session",
            str(session_dir / "session.jsonl"),
            cwd=workspace,
            env=env,
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self.max_bytes,
        )
        self.revision_dir = revision_dir
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
            if self.provider == "openrouter":
                compat = model.get("compat") or {}
                if (
                    state.get("thinkingLevel") != "medium"
                    or model.get("api") != "openai-completions"
                    or model.get("baseUrl") != OPENROUTER_BASE_URL
                    or not model.get("reasoning")
                    or compat.get("openRouterRouting") != pinned_route(self.routing_provider)
                    or compat.get("thinkingFormat") != "openrouter"
                ):
                    raise ValueError("Pi worker routing or reasoning policy mismatch")
            if state.get("isStreaming") or state.get("isCompacting"):
                raise RuntimeError("Pi has unsettled prior work")
            return
        raise RuntimeError("Pi exited before model verification")

    async def _openrouter_result(self, message: dict) -> str:
        """Pi reports the gateway as provider. Check the actual generation upstream."""
        import httpx

        generation = message.get("responseId")
        if (message.get("provider") != self.provider
                or message.get("model") != self.model
                or not isinstance(generation, str) or not 1 <= len(generation) <= 256
                or message.get("stopReason") != "stop"):
            raise ValueError("Missing or mismatched Pi generation identity")
        content = message.get("content", [])
        if any(block.get("type") not in {"text", "thinking"} for block in content):
            raise ValueError("Worker returned unexpected content or tool call")
        text = "".join(block["text"] for block in content if block["type"] == "text")
        if not text.strip():
            raise ValueError("Pi returned no usable text")
        async with httpx.AsyncClient(timeout=10) as client:
            # Generation accounting can briefly lag a completed stream.
            for attempt in range(4):
                response = await client.get(
                    OPENROUTER_BASE_URL + "/generation", params={"id": generation},
                    headers={"Authorization": "Bearer " + self.env["OPENROUTER_API_KEY"]},
                )
                if response.status_code != 404 or attempt == 3:
                    break
                await asyncio.sleep(0.3 * (2 ** attempt))
            response.raise_for_status()
            record = response.json().get("data") or {}
        if (record.get("id") != generation or record.get("model") != self.model
                or record.get("provider_name") != self.serving_name
                or record.get("cancelled") is not False
                or record.get("finish_reason") != "stop"):
            raise ValueError("OpenRouter generation route or completion mismatch")
        self.verified_provider = record["provider_name"]
        return text

    async def _turn(self, prompt: str) -> str:
        turn_id, result_id = uuid.uuid4().hex, uuid.uuid4().hex
        await self._send({"id": turn_id, "type": "prompt", "message": prompt})
        accepted = ended = requested = False
        assistant_message = {}
        self.verified_provider = None
        total = 0
        while line := await self.process.stdout.readline():
            total += len(line)
            if total > self.max_bytes:
                raise ValueError("Pi output exceeds limit")
            record = json.loads(line)
            kind = record.get("type")
            if kind == "message_update" and self.on_text_delta is not None:
                update = record.get("assistantMessageEvent") or {}
                delta = update.get("delta")
                if update.get("type") == "text_delta" and isinstance(delta, str) and delta:
                    self.on_text_delta(self.revision_dir, delta)
            elif kind == "message_end":
                message = record.get("message", {})
                if message.get("role") == "assistant":
                    if message.get("stopReason") in {"error", "aborted"}:
                        raise RuntimeError(
                            "Pi inference failed or was aborted"
                        )
                    ended = True
                    assistant_message = message
            elif kind == "tool_execution_start" or (
                self.provider == "openrouter" and kind == "auto_retry_start"
            ):
                raise RuntimeError("Worker attempted a disabled tool or retry")
            elif kind == "response":
                if not record.get("success"):
                    raise RuntimeError("Pi rejected a protocol command")
                if record.get("id") == turn_id:
                    disposition = record.get("data", {}).get("disposition")
                    # Pi 0.84.2 acknowledges successful preflight without a
                    # disposition. Settlement and a final assistant message
                    # are still required below.
                    if disposition not in {None, "started"}:
                        raise RuntimeError("Pi did not start a model run")
                    accepted = True
                elif record.get("id") == result_id and requested:
                    text = record.get("data", {}).get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("Pi returned no usable text")
                    return text
            elif kind == "agent_settled" and not requested:
                if not accepted or not ended or record.get("aborted"):
                    raise RuntimeError("Pi failed or aborted before settlement")
                if self.provider == "openrouter":
                    return await self._openrouter_result(assistant_message)
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
        try:
            if process is not None:
                process.stdin.close()
                drain = asyncio.create_task(_drain(process.stdout))
                await _reap(process)
                await asyncio.gather(drain, self.diagnostics)
        finally:
            if self.agent_directory is not None:
                self.agent_directory.cleanup()
                self.agent_directory = None
        self.diagnostics = None
        self.revision_dir = None

    async def close(self) -> None:
        async with self.lock:
            await self._close_process()
