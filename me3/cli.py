"""
Executable preliminary demos. No microphone or model use unless requested.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import tomllib
from pathlib import Path

from .backends import make_backend
from .core import Controller, Supervisor

HELP = """Plain text: ask the foreground agent.
/task REQUEST          submit independent background work
/jobs                  list job states
/update ID REQUEST     revise a running job
/cancel ID             cancel only that job
/focus ID              switch context to a job (/focus clears it)
/result ID             display a completed artifact
/stop                  interrupt the foreground, keep jobs running
/quit                  shutdown; unfinished jobs become interrupted
IDs are printed in full. No automatic semantic routing or external actions.
"""


async def chat(controller) -> None:
    print(HELP)
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin,
    )
    responses = set()

    async def answer(text):
        try:
            print("ASSISTANT:", await controller.ask(text), flush=True)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print("ERROR:", type(exc).__name__, str(exc), file=sys.stderr)

    async def notify():
        while True:
            await asyncio.sleep(0.2)
            for job in controller.notices():
                print("READY (focus unchanged):", job["id"], flush=True)

    notifier = asyncio.create_task(notify())
    try:
        while True:
            line = (await reader.readline()).decode("utf-8", errors="replace")
            if not line or line.strip() == "/quit":
                break
            line = line.strip()
            if not line:
                continue
            try:
                command, _, rest = line.partition(" ")
                if command == "/task":
                    print(
                        json.dumps(controller.supervisor.submit(rest)),
                        flush=True,
                    )
                elif command == "/jobs":
                    print(
                        json.dumps(controller.supervisor.list(), indent=2),
                        flush=True,
                    )
                elif command == "/cancel":
                    print(
                        json.dumps(controller.supervisor.cancel(rest)),
                        flush=True,
                    )
                elif command == "/update":
                    job_id, _, request = rest.partition(" ")
                    print(
                        json.dumps(
                            controller.supervisor.update(job_id, request),
                        ),
                        flush=True,
                    )
                elif command == "/focus":
                    controller.set_focus(rest or None)
                    print("FOCUS:", controller.focus, flush=True)
                elif command == "/result":
                    print(controller.supervisor.result(rest), flush=True)
                elif command == "/stop":
                    controller.interrupt()
                elif command.startswith("/"):
                    print(HELP)
                else:
                    task = asyncio.create_task(answer(line))
                    responses.add(task)
                    task.add_done_callback(responses.discard)
                    await asyncio.sleep(0)
            except (ValueError, RuntimeError, KeyError) as exc:
                print("ERROR:", str(exc), file=sys.stderr)
    finally:
        transport.close()
        notifier.cancel()
        for task in responses:
            task.cancel()
        await controller.close()
        await asyncio.gather(notifier, *responses, return_exceptions=True)


async def demo(controller) -> None:
    job = controller.supervisor.submit(
        "Write a short latency experiment plan.",
    )
    await asyncio.sleep(0.01)
    print("Background job:", job["id"])
    print("Foreground:", await controller.ask("Explain an RNN."))
    assert controller.supervisor.get(job["id"])["status"] == "running"
    controller.interrupt()
    controller.user_speaking = True
    await controller.supervisor.wait(job["id"])
    assert not controller.notices()
    controller.user_speaking = False
    assert len(controller.notices()) == 1
    assert controller.focus is None
    print(
        (
            "PASS: independent job survived "
            "interruption; notice deferred; focus "
            "unchanged."
        ),
    )
    print("Artifact:", controller.supervisor.get(job["id"])["artifact"])
    print(
        (
            "SIMULATION ONLY: no OnIt, ASR, TTS, "
            "microphone or physical latency evidence."
        ),
    )


async def run(args) -> None:
    config = {}
    if args.config:
        with args.config.open("rb") as stream:
            config = tomllib.load(stream)
    if args.mode == "mcp-speech":
        from .mcp_server import speech_server
        from .speech import make_speech

        await speech_server(make_speech(config)).run_stdio_async()
        return
    if args.mode == "benchmark":
        from .benchmark import benchmark

        if config.get("backend", "mock") != "mock":
            raise ValueError(
                "This benchmark measures only the explicit simulator.",
            )
        await benchmark(args.output, args.trials)
        print("SIMULATOR benchmark written to", args.output)
        return
    if args.mode == "demo":
        if config.get("backend", "mock") != "mock":
            raise ValueError(
                "demo is simulator-only; use chat or voice for OnIt.",
            )
    backend = make_backend(config)
    root = args.state or Path.home() / ".local" / "state" / "me3"
    supervisor = Supervisor(
        root,
        backend,
        workers=int(config.get("workers", 1)),
    )
    controller = Controller(supervisor, backend)
    try:
        if args.mode == "mcp":
            from .mcp_server import control_server

            await control_server(supervisor, controller).run_stdio_async()
        elif args.mode == "voice":
            if args.config is None:
                raise ValueError(
                    "voice requires --config with speech inference endpoints.",
                )
            from .voice import voice_session

            print("BACKEND:", config.get("backend", "mock"), flush=True)
            await voice_session(controller, config, args.config)
        elif args.mode == "chat":
            print("BACKEND:", config.get("backend", "mock"), flush=True)
            await chat(controller)
        else:
            await demo(controller)
    finally:
        await controller.close()
        await supervisor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=["demo", "chat", "voice", "mcp", "mcp-speech", "benchmark"],
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark-output"),
    )
    parser.add_argument("--trials", type=int, default=20)
    args = parser.parse_args()
    try:
        if args.mode == "demo" and args.state is None:
            with tempfile.TemporaryDirectory(prefix="me3-demo-") as directory:
                args.state = Path(directory)
                asyncio.run(run(args))
        else:
            asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
