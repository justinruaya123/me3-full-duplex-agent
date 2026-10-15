"""Explicit simulator and isolated, locally executed OnIt adapters."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

ONIT_REVISION = "0a9c391560a7767f36fd56ddbe81749b44b54fec"


class MockBackend:
    """A deterministic simulator, never an automatic inference fallback."""

    async def run(
        self, prompt: str, workspace: Path, *, foreground: bool = False
    ) -> str:
        await asyncio.sleep(0.03 if foreground else 0.7)
        if foreground:
            return "[SIMULATED] The foreground remains responsive."
        return (
            "# Simulated artifact\n\nNo model inference "
            "was performed.\n\nRequest: "
        ) + prompt


class ProcessBackend:
    """One local process group per request; safe to cancel independently."""

    def __init__(
        self, command: list[str], *, timeout: float = 180,
        settings: dict | None = None,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self.settings = settings or {}
        self.active_pids: set[int] = set()

    async def run(
        self, prompt: str, workspace: Path, *, foreground: bool = False
    ) -> str:
        workspace = workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        request = workspace / "request.json"
        output = workspace / "response.json"
        output.unlink(missing_ok=True)
        request.write_text(json.dumps({
            "prompt": prompt, "foreground": foreground,
            "workspace": str(workspace), "settings": self.settings,
        }), encoding="utf-8")
        with (workspace / "runner.log").open("wb") as log:
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                *self.command, str(request), str(output),
                stdout=log, stderr=log, start_new_session=True,
            ))
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                process = await spawn
                await self._stop(process)
                raise
            self.active_pids.add(process.pid)
            try:
                await asyncio.wait_for(process.wait(), self.timeout)
                if process.returncode:
                    raise RuntimeError(
                        f"Local agent exited with code {process.returncode}; "
                        "inspect runner.log."
                    )
                if not output.exists() or output.stat().st_size > 1024 * 1024:
                    raise RuntimeError(
                        (
                            "Local agent returned no result or an "
                            "oversized result."
                        ),
                    )
                result = json.loads(output.read_text(encoding="utf-8"))
                if not isinstance(
                    result.get("text"),
                    str,
                ) or not result["text"].strip():
                    raise RuntimeError(
                        "Local agent returned an invalid text result.",
                    )
                return result["text"]
            finally:
                if process.returncode is None:
                    await self._stop(process)
                self.active_pids.discard(process.pid)

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 1)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


def make_backend(config: dict):
    mode = config.get("backend", "mock")
    if mode == "mock":
        return MockBackend()
    if mode != "onit":
        raise ValueError("backend must be 'mock' or 'onit'.")
    settings = dict(config.get("onit", {}))
    if not settings.get(
        "checkout",
    ) or not settings.get("model") or not settings.get("host"):
        raise ValueError(
            "OnIt mode requires onit.checkout, onit.model and onit.host.",
        )
    executable = str(Path(settings.pop("python", sys.executable)).expanduser())
    settings["checkout"] = str(
        Path(settings["checkout"]).expanduser().resolve(),
    )
    settings.setdefault("revision", ONIT_REVISION)
    return ProcessBackend(
        [executable, str(Path(__file__).with_name("onit_runner.py"))],
        settings=settings,
    )
