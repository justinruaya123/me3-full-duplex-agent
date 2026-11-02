"""Local harness adapters. Provider inference may be remote; jobs are not."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Mapping

HERMES_REVISION = "2b31d7b283191b8069311fd3514ee89419f76516"
PI_SOURCE_REVISION = "3e0eec29f50e7861e9db91f2d12723267411b4f3"


async def _drain(reader: asyncio.StreamReader) -> None:
    # Discard unread output without retaining provider logs or secrets.
    while await reader.read(8192):
        pass


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 1)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


def _text(record: dict) -> str:
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Harness returned no usable text")
    return text


class JsonProcessBackend:
    """One isolated process per request; no shell and no implicit fallback.

    This is an isolation baseline, not a persistent low-latency worker pool.
    Command/extra environment are operator configuration, never model output.
    """

    def __init__(
        self, command: tuple[str, ...], *, timeout: float = 180,
        max_bytes: int = 1_048_576, env: Mapping[str, str] | None = None,
    ) -> None:
        if not command or timeout <= 0 or max_bytes < 1024:
            raise ValueError("Invalid harness process configuration")
        self.command = command
        self.timeout, self.max_bytes = timeout, max_bytes
        self.env = dict(env or {})

    async def _exchange(self, process, prompt: str, foreground: bool) -> str:
        request = json.dumps({"prompt": prompt, "foreground": foreground})
        process.stdin.write(request.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        chunks, size = [], 0
        while chunk := await process.stdout.read(8192):
            size += len(chunk)
            if size > self.max_bytes:
                raise ValueError("Harness output exceeded its limit")
            chunks.append(chunk)
        await process.wait()
        if process.returncode:
            raise RuntimeError(f"Harness exit code: {process.returncode}")
        return _text(json.loads(b"".join(chunks)))

    async def run(
        self, prompt: str, workspace: Path, *, foreground: bool = False,
    ) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A prompt is required")
        workspace.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **self.env}
        env["HERMES_HOME"] = str(workspace.resolve() / ".hermes")
        process = await asyncio.create_subprocess_exec(
            *self.command, cwd=workspace, env=env, start_new_session=True,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=self.max_bytes,
        )
        diagnostics = asyncio.create_task(_drain(process.stderr))
        try:
            async with asyncio.timeout(self.timeout):
                return await self._exchange(process, prompt, foreground)
        finally:
            process.stdin.close()
            # An output-limit error can leave stdout flow-control paused.
            # Drain before waiting so process exit also closes its pipes.
            remaining_output = asyncio.create_task(_drain(process.stdout))
            try:
                await _reap(process)
                await asyncio.gather(remaining_output, diagnostics)
            finally:
                remaining_output.cancel()
                diagnostics.cancel()
                await asyncio.gather(
                    remaining_output, diagnostics, return_exceptions=True,
                )


class PiBackend(JsonProcessBackend):
    """Pi RPC: await agent_settled, not prompt acceptance or agent_end."""

    async def _exchange(self, process, prompt: str, foreground: bool) -> str:
        async def send(record):
            process.stdin.write(json.dumps(record).encode("utf-8") + b"\n")
            await process.stdin.drain()

        await send({"id": "turn", "type": "prompt", "message": prompt})
        requested_result = False
        total = 0
        while line := await process.stdout.readline():
            total += len(line)
            if total > self.max_bytes:
                raise ValueError("Pi event stream exceeded its limit")
            record = json.loads(line)
            kind = record.get("type")
            if kind == "message_end":
                message = record.get("message", {})
                if message.get("stopReason") in {"error", "aborted"}:
                    raise RuntimeError("Pi run failed or was aborted")
            if kind == "response":
                if not record.get("success"):
                    raise RuntimeError("Pi rejected a protocol command")
                data = record.get("data", {})
                if (record.get("id") == "turn"
                        and data.get("disposition") == "handled"):
                    raise RuntimeError("Pi handled prompt without a run")
                if record.get("id") == "result" and requested_result:
                    text = _text(data)
                    process.stdin.close()
                    await process.wait()
                    if process.returncode:
                        raise RuntimeError("Pi failed during shutdown")
                    return text
            if kind == "agent_settled" and not requested_result:
                requested_result = True
                await send({"id": "result", "type": "get_last_assistant_text"})
        raise RuntimeError("Pi exited before a settled result was received")


def hermes_backend(env: Mapping[str, str] | None = None) -> JsonProcessBackend:
    values = os.environ if env is None else env
    required = ("ME3_HERMES_ROOT", "ME3_HERMES_PYTHON", "ME3_MODEL")
    if any(not values.get(key) for key in required):
        raise ValueError("Set " + ", ".join(required))
    root = Path(values["ME3_HERMES_ROOT"]).expanduser().resolve()
    python = Path(values["ME3_HERMES_PYTHON"]).expanduser().resolve()
    if not (root / "run_agent.py").is_file() or not python.is_file():
        raise ValueError("Hermes checkout or interpreter does not exist")
    runner = Path(__file__).with_name("hermes_runner.py").resolve()
    return JsonProcessBackend(
        (str(python), str(runner)),
        env={**values, "ME3_HERMES_ROOT": str(root),
             "ME3_HERMES_REVISION": HERMES_REVISION},
    )


def configured_backend():
    name = os.environ.get("ME3_HARNESS", "hermes")
    if name == "hermes":
        return hermes_backend()
    if name == "pi":
        binary = Path(os.environ.get("ME3_PI_BIN", "")).expanduser().resolve()
        model = os.environ.get("ME3_MODEL")
        if not binary.is_file() or not model:
            raise ValueError("Set ME3_PI_BIN to pi's path and ME3_MODEL")
        command = (
            str(binary), "--mode", "rpc", "--no-session", "--no-tools",
            "--no-extensions", "--no-mcp", "--no-skills",
            "--no-prompt-templates", "--no-context-files", "--model", model,
        )
        return PiBackend(command)
    raise ValueError("ME3_HARNESS must be hermes or pi; no implicit mocks")
