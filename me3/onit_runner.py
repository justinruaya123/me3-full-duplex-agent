"""Run the pinned OnIt API locally in a separate Python environment.

No speech model or autonomous agent runs on the inference host. Default OnIt
shell/network tools and harness code execution are explicitly disabled here.
This adapter is NOT an OS sandbox.
Do not enable arbitrary tools in this process.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


def build_config(request: dict) -> dict:
    settings = request["settings"]
    workspace = Path(request["workspace"])
    return {
        "serving": {
            "host": settings["host"], "model": settings["model"],
            "host_key": os.environ.get("ME3_MODEL_API_KEY", ""),
            "think": False,
            "max_tokens": 256 if request["foreground"] else 2048,
            "harness_tools": False, "code_execution": False,
        },
        "learn": {"enabled": False},
        "stream": False, "loop": True, "verbose": False,
        "show_logs": False, "timeout": 90, "prompt_in_process": True,
        "data_path": str(workspace),
        "session_path": str(workspace / "session.jsonl"),
        "mcp": {"servers": [
            {"name": "PromptsMCPServer", "enabled": False},
            {"name": "ToolsLocalMCPServer", "enabled": False},
            {"name": "ToolsNetMCPServer", "enabled": False},
        ]},
    }


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    checkout = Path(request["settings"]["checkout"]).resolve()
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=5,
    ).stdout.strip()
    if revision != request["settings"]["revision"]:
        raise RuntimeError(
            "OnIt checkout does not match the configured commit.",
        )
    # Import the genuine SDK before OnIt's src/mcp can shadow it.
    import mcp.types  # noqa: F401
    import fastmcp.client  # noqa: F401
    import fastmcp.server  # noqa: F401
    import fastmcp.server.context  # noqa: F401

    sys.path.insert(0, str(checkout))
    from src.onit import OnIt

    agent = OnIt(
        build_config(request),
    )  # Constructor needs no running event loop.
    registry = getattr(agent, "tool_registry", None)
    if registry and getattr(registry, "tools", {}):
        raise RuntimeError(
            "Unexpected tool registration; this adapter is tool-disabled.",
        )

    async def execute() -> str:
        return await agent.process_task(
            request["prompt"],
            session_path=str(Path(request["workspace"]) / "session.jsonl"),
            data_path=request["workspace"],
            safety_queue=asyncio.Queue(), stats={},
        )

    answer = asyncio.run(execute())
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError(
            "OnIt produced no answer; no simulator fallback is allowed.",
        )
    Path(sys.argv[2]).write_text(
        json.dumps({"text": answer}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
