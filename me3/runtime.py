"""Long-lived job ownership, independent of voice transport/session lifetime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

from me3.core import Supervisor
from me3.duplex import DuplexController
from me3.jobs import OwnedJobs
from me3.preview import PreviewManager
from me3.website import WebsiteWorker, prepare_website


class AgentRuntime:
    def __init__(
        self, root: Path, worker, foreground, *,
        memory_enabled: bool | None = None,
    ) -> None:
        from me3.memory import MemoryStore

        if memory_enabled is None:
            value = os.environ.get("ME3_MEMORY_ENABLED", "1")
            if value not in {"0", "1"}:
                raise ValueError("ME3_MEMORY_ENABLED must be 0 or 1")
            memory_enabled = value == "1"
        self.memory = None
        self._memory_jobs: dict[str, str] = {}
        self.worker = WebsiteWorker(
            worker, memory_context=self._worker_context
        )
        self.supervisor = Supervisor(
            root,
            self.worker,
            workers=1,
            max_pending=5,  # One active job plus four waiting.
            timeout=600,
            prepare_result=prepare_website,
        )
        if memory_enabled:
            try:
                # Only fingerprints cross into the durable job store. Saved
                # requests already belong to the jobs that authorized them.
                self.supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_context_use (
                    job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL,
                    personal INTEGER NOT NULL, digest TEXT NOT NULL)""")
                self.memory = MemoryStore(
                    self.supervisor.root / "memory.sqlite3"
                )
            except Exception:
                # Initialization is synchronous: no job tasks exist yet.
                self.supervisor.db.close()
                self.supervisor._lock.close()
                self.supervisor.closed = True
                raise
        self.foreground = foreground
        self.sessions: set[DuplexController] = set()
        self.previews = PreviewManager()
        self.closed = False

    def open_session(
        self, speak, stop, *, owner=None, remember=True, **options
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
        session.jobs.on_deferred = self._notice_deferred
        if self.memory is not None and remember:
            from me3.memory import SessionMemory

            session.memory = SessionMemory(
                self.memory, session.jobs,
                lambda: (
                    not session._closed and session.jobs.authorized()
                    and session.delivery_authorized()
                ),
                self._memory_changed,
            )
            session.jobs.site_context = session.memory.worker_context
            session.jobs.submitted = lambda job_id: self._remember_job(
                session, job_id
            )
        self.sessions.add(session)
        return session

    def _remember_job(self, session, job_id: str) -> None:
        memory = session.memory
        owner = session.jobs.owner
        if (
            owner and memory.authorized()
            and memory.owner in {None, owner}
        ):
            self._memory_jobs[job_id] = owner

    def _worker_context(self, prompt: str, workspace: Path) -> str:
        owner = self._memory_jobs.pop(workspace.parent.name, None)
        if self.memory is None or owner is None:
            return ""
        from me3.memory import personal_site

        job_id = workspace.parent.name
        revision = self.supervisor.get(job_id)["revision"]
        previous = self.supervisor.db.execute(
            "SELECT personal FROM job_context_use WHERE job_id=? AND owner=?",
            (job_id, owner),
        ).fetchone()
        personal = personal_site(prompt) or bool(previous and previous["personal"])
        lookup = prompt + " about me" if personal else prompt
        snapshot = self.memory.context(owner, lookup, worker=True)
        data = json.loads(snapshot) if snapshot else {}
        if personal and not data.get("public_approved"):
            raise ValueError("Personal website needs a public-approved profile field")
        with self.supervisor.db:
            if any(data.values()):
                self.supervisor.db.execute(
                    "INSERT OR REPLACE INTO job_context_use VALUES (?,?,?,?,?)",
                    (job_id, owner, revision, int(personal), self._digest(snapshot)),
                )
            else:
                self.supervisor.db.execute(
                    "DELETE FROM job_context_use WHERE job_id=?", (job_id,)
                )
        return snapshot

    @staticmethod
    def _digest(snapshot: str) -> str:
        return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()

    def _memory_changed(self, owner: str) -> None:
        from me3.memory import ScopeAmbiguity

        uses = self.supervisor.db.execute(
            "SELECT * FROM job_context_use WHERE owner=?", (owner,)
        ).fetchall()
        for use in uses:
            job = self.supervisor.get(use["job_id"])
            if (job["revision"] != use["revision"]
                    or job["status"] not in {"running", "queued", "completed"}):
                continue
            lookup = job["prompt"] + " about me" if use["personal"] else job["prompt"]
            try:
                snapshot = self.memory.context(owner, lookup, worker=True)
            except ScopeAmbiguity:
                snapshot = ""
            if self._digest(snapshot) != use["digest"]:
                self.supervisor.invalidate_context(job["id"], job["revision"])
                self.previews.stop(job["id"])
                self._job_changed(job["id"])
        for session in self.sessions:
            if (
                session.memory is not None and session.jobs.owner == owner
                and not session._closed
            ):
                session.invalidate_memory()

    def _notice_deferred(self, job_id: str) -> None:
        for session in self.sessions:
            if job_id in session.notice_sources:
                session.invalidate_job(job_id)

    def _job_changed(self, job_id: str) -> None:
        self._memory_jobs.pop(job_id, None)
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
        if hasattr(self.foreground, "close"):
            await self.foreground.close()
        if self.memory is not None:
            self.memory.close()
        self._memory_jobs.clear()


async def start_local_voice(runtime, *, on_stage=None, on_voice=None,
                            terminal_demo_owner=None, local_mcp=False):
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
    # The pinned Pipecat transport closes its streams but leaves its PyAudio
    # instance initialized. Balance that allocation on every mode change.
    try:
        run, voice_control = await build(
            transport, runtime.supervisor.root, runtime=runtime, on_stage=on_stage,
            on_voice=on_voice,
            profile="terminal-demo" if terminal_demo_owner else "ownership",
            terminal_demo_owner=terminal_demo_owner, local_mcp=local_mcp,
        )
        task = asyncio.create_task(run)
    except BaseException:
        transport._pyaudio.terminate()
        raise
    task.add_done_callback(lambda _: transport._pyaudio.terminate())
    return task, voice_control


async def _console(args) -> None:
    import sys

    from me3.foreground import configured_foreground
    from me3.harnesses import configured_backend

    runtime = AgentRuntime(
        Path(args.state).expanduser(),
        configured_backend(),
        configured_foreground(),
    )
    voice_task = control = None

    async def speak(text):
        print("ASSISTANT [console delivery]: " + text, flush=True)
        return True

    async def stop():
        pass

    session = runtime.open_session(speak, stop, owner=args.owner)

    session.companion = lambda text: print(text, flush=True)

    try:
        if args.voice:
            voice_task, control = await start_local_voice(runtime)
        print(
            "ME3 runtime: jobs persist across /end. /quit shuts down runtime.\n"
            "/site REQUEST | /jobs | /status ID | /result ID | /revise ID REQUEST\n"
            "/cancel ID | /preview ID | /focus ID | go back | /voice | /end\n"
            "/enroll OWNER (after wake) | /mute | /start OWNER\n"
            "/memory [on|off|clear] | /remember KEY = VALUE\n"
            "/project NAME = DETAILS | /forget KEY | /recall QUERY",
            flush=True,
        )
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: protocol,
            sys.stdin,
        )
        line_task = None
        try:
            while True:
                if line_task is None:
                    line_task = asyncio.create_task(reader.readline())
                watching = [line_task] + ([voice_task] if voice_task else [])
                done, _ = await asyncio.wait(
                    watching, return_when=asyncio.FIRST_COMPLETED,
                    timeout=0.1 if voice_task is None and not session._closed else None,
                )
                if not done:
                    session.poll()
                    continue
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
                if line_task not in done:
                    continue
                line = line_task.result()
                line_task = None
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
                        session.companion = lambda value: print(value, flush=True)
                    elif text == "/voice":
                        if voice_task is None:
                            voice_task, control = await start_local_voice(runtime)
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
            if line_task:
                line_task.cancel()
                await asyncio.gather(line_task, return_exceptions=True)
            transport.close()
    finally:
        if control:
            await control()
        if voice_task:
            await asyncio.gather(voice_task, return_exceptions=True)
        await runtime.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Persistent ME3 runtime; independent foreground and worker roles"
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
