"""Long-lived job ownership, independent of voice transport/session lifetime."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from me3.core import Supervisor
from me3.duplex import DuplexController
from me3.jobs import OwnedJobs
from me3.preview import PreviewManager
from me3.website import WebsiteWorker, prepare_website


class AgentRuntime:
    def __init__(self, root: Path, worker, foreground) -> None:
        self.worker = WebsiteWorker(worker)
        self.supervisor = Supervisor(
            root,
            self.worker,
            timeout=600,
            prepare_result=prepare_website,
        )
        self.foreground = foreground
        self.sessions: set[DuplexController] = set()
        self.previews = PreviewManager()
        self.closed = False

    def open_session(
        self, speak, stop, *, owner=None, **options
    ) -> DuplexController:
        if self.closed:
            raise RuntimeError("Runtime is closed")
        session = DuplexController(
            OwnedJobs(
                self.supervisor,
                owner,
                uuid.uuid4().hex,
                previews=self.previews,
                changed=self._job_changed,
            ),
            self.foreground,
            speak,
            stop,
            **options,
        )
        session.jobs.authorized = lambda: not session._closed
        self.sessions.add(session)
        return session

    def _job_changed(self, job_id: str) -> None:
        for session in self.sessions:
            session.invalidate_job(job_id)

    async def end_session(self, session: DuplexController) -> None:
        await session.close()
        self.previews.stop_session(session.jobs.session_id)
        self.sessions.discard(session)

    async def close(self) -> None:
        """Explicit runtime shutdown; pending jobs become interrupted."""
        if self.closed:
            return
        self.closed = True
        for session in list(self.sessions):
            await self.end_session(session)
        await self.previews.close()
        await self.supervisor.close()
        await self.worker.close()


async def _console(args) -> None:
    import os
    import sys

    from me3.configuration import ForegroundConfig
    from me3.foreground import ForegroundBackend
    from me3.harnesses import configured_backend

    runtime = AgentRuntime(
        Path(args.state).expanduser(),
        configured_backend(),
        ForegroundBackend(ForegroundConfig.from_env(os.environ)),
    )
    voice_task = control = None

    async def speak(text):
        print("ASSISTANT [console delivery]: " + text, flush=True)
        return True

    async def stop():
        pass

    session = runtime.open_session(speak, stop, owner=args.owner)

    async def start_voice():
        from pipecat.transports.local.audio import (
            LocalAudioTransport,
            LocalAudioTransportParams,
        )

        from me3.duplex_voice import build

        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
                audio_out_10ms_chunks=2,
            )
        )
        run, voice_control = await build(
            transport, runtime.supervisor.root, runtime=runtime
        )
        return asyncio.create_task(run), voice_control

    try:
        if args.voice:
            voice_task, control = await start_voice()
        print(
            "ME3 runtime: Pi jobs persist across /end. /quit shuts down runtime.\n"
            "/site REQUEST | /jobs | /status ID | /result ID | /revise ID REQUEST\n"
            "/cancel ID | /preview ID | /focus ID | go back | /voice | /end\n"
            "/enroll OWNER (after wake) | /mute | /start OWNER",
            flush=True,
        )
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: protocol,
            sys.stdin,
        )
        try:
            while True:
                line_task = asyncio.create_task(reader.readline())
                watching = [line_task] + ([voice_task] if voice_task else [])
                done, _ = await asyncio.wait(
                    watching, return_when=asyncio.FIRST_COMPLETED
                )
                if voice_task and voice_task in done:
                    try:
                        voice_task.result()
                    except Exception as exc:
                        print(
                            "Voice stopped: "
                            + type(exc).__name__
                            + "; delegated work continues.",
                            flush=True,
                        )
                    voice_task = control = None
                    if not line_task.done():
                        # Keep exactly one pending read; never lose terminal input.
                        line = await line_task
                    else:
                        line = line_task.result()
                else:
                    line = line_task.result()
                if not line:
                    # EOF detaches console; drain submitted work before shutdown.
                    for job in runtime.supervisor.list():
                        await runtime.supervisor.wait(job["id"])
                    break
                text = line.decode().strip()
                if not text:
                    continue
                try:
                    if text == "/quit":
                        break
                    if text == "/end":
                        if control:
                            await control()
                            await voice_task
                            voice_task = control = None
                        await runtime.end_session(session)
                        print(
                            "Session ended; jobs continue. /start OWNER reconnects.",
                            flush=True,
                        )
                    elif text.startswith("/start "):
                        await runtime.end_session(session)
                        session = runtime.open_session(
                            speak, stop, owner=text[7:].strip()
                        )
                    elif text == "/voice":
                        if voice_task is None:
                            voice_task, control = await start_voice()
                    elif text == "/mute":
                        if control:
                            await control.mute()
                        print(
                            "Voice muted and voice reference erased. End/start voice to renew.",
                            flush=True,
                        )
                    elif text.startswith("/enroll "):
                        if control is None:
                            raise ValueError("Start voice first")
                        control.enroll(text[8:].strip())
                        print(
                            "Enrollment armed; speak a clean phrase of at least 2 seconds.",
                            flush=True,
                        )
                    else:
                        print(
                            "CONTROL: " + await session.accept(text),
                            flush=True,
                        )
                except (
                    ValueError,
                    RuntimeError,
                    PermissionError,
                    KeyError,
                ) as exc:
                    print("Unavailable: " + str(exc), flush=True)
        finally:
            transport.close()
    finally:
        if control:
            await control()
        if voice_task:
            await asyncio.gather(voice_task, return_exceptions=True)
        await runtime.close()


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Persistent ME3 runtime; explicit Pi/foreground roles"
    )
    parser.add_argument(
        "--state", default=os.environ.get("ME3_STATE_DIR", ".local/runtime")
    )
    parser.add_argument(
        "--owner",
        default="local-operator",
        help="Trusted local console identity",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Attach the actual local Pipecat audio transport",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_console(args))
    except (ValueError, RuntimeError) as exc:
        parser.exit(
            2,
            "ME3 configuration: " + str(exc) + "\nRun python -m me3.doctor.\n",
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
