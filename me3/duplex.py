"""Transport-neutral floor policy; lexical rules are not an acoustic model."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from contextlib import aclosing

from me3.incremental import TranscriptRevision, clauses
from pathlib import Path
from typing import Awaitable, Callable, Protocol


class Backend(Protocol):
    async def run(
        self, prompt: str, workspace: Path, *, foreground: bool = False,
    ) -> str: ...


class Jobs(Protocol):
    root: Path

    def submit(self, prompt: str) -> dict: ...
    def list(self) -> list[dict]: ...
    def get(self, job_id: str) -> dict: ...
    def acknowledge(self, job_id: str, revision: int) -> None: ...
    def trace(self, event: str, **fields: object) -> None: ...


def classify_overlap(
    text: str, speaking: bool, *, addressed: bool | None = None,
) -> str:
    """Match whole phrases; unknown addressee is not background rejection."""
    words = re.sub(r"[^\w\s]", " ", text.lower())
    words = " ".join(words.split())
    if addressed is False:
        return "ignore"
    if words in {"stop", "stop talking", "stop speaking", "be quiet"}:
        return "stop"
    acknowledgments = {
        "mm hmm", "mmhmm", "mhm", "uh huh", "yeah", "yes",
        "right", "okay", "ok",
    }
    if speaking and words in acknowledgments:
        return "backchannel"
    return "turn"


class SupervisorJobs:
    """Adapt the existing Supervisor without changing its job semantics."""

    def __init__(self, supervisor) -> None:
        self.supervisor = supervisor
        self.root = supervisor.root

    def submit(self, prompt: str) -> dict:
        return self.supervisor.submit(prompt)

    def list(self) -> list[dict]:
        return self.supervisor.list()

    def get(self, job_id: str) -> dict:
        return self.supervisor.get(job_id)

    def acknowledge(self, job_id: str, revision: int) -> None:
        with self.supervisor.db:
            self.supervisor.db.execute(
                "UPDATE jobs SET notified=1 WHERE id=? AND revision=? "
                "AND status='completed'", (job_id, revision),
            )

    def trace(self, event: str, **fields: object) -> None:
        self.supervisor.trace(event, **fields)


class DuplexController:
    """One foreground speaker, independent jobs, and revision-fenced notices.

    ``speak`` returns True only after playback completion, not TTS submission.
    ``stop`` must flush queued output. It must never cancel background jobs.
    A speech stop is not a transcript boundary: notices wait for final ASR.
    """

    def __init__(
        self, jobs: Jobs, backend: Backend,
        speak: Callable[[str], Awaitable[bool]],
        stop: Callable[[], Awaitable[None]], *,
        clock: Callable[[], float] = time.monotonic,
        quiet_seconds: float = 0.8,
        is_playing: Callable[[], bool] | None = None,
    ) -> None:
        if quiet_seconds < 0:
            raise ValueError("quiet_seconds must be nonnegative")
        self.jobs, self.backend = jobs, backend
        self.speak, self.stop, self.clock = speak, stop, clock
        self.quiet_seconds, self.is_playing = quiet_seconds, is_playing
        self.history: list[dict[str, str]] = []
        self.focus: str | None = None
        self.user_speaking = False
        self.turn_open = False
        self.epoch = 0
        self._active: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._speaking = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._turn_final = asyncio.Event()
        self._turn_final.set()
        self._last_activity = clock()
        self._last_backchannel = float("-inf")
        self._pending = ""
        self._closed = False
        self._transcripts: dict[tuple[str, str], tuple[int, bool]] = {}
        self._transcript_session: str | None = None

    @property
    def busy(self) -> bool:
        return self._active is not None and not self._active.done()

    def user_started(self) -> None:
        self.user_speaking = True
        self.turn_open = True
        self._idle.clear()
        self._turn_final.clear()
        self._last_activity = self.clock()
        self.jobs.trace("user_started")

    def user_stopped(self) -> None:
        self.user_speaking = False
        self._idle.set()
        self._last_activity = self.clock()
        self.jobs.trace("user_stopped_asr_pending")

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._active = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _interrupt(self) -> None:
        self.epoch += 1
        old = self._active
        self._active = None
        if old and not old.done():
            old.cancel()
        self._speaking = False
        await self.stop()
        self.jobs.trace("speech_cancelled", epoch=self.epoch)

    async def transcript(self, event: TranscriptRevision, **evidence) -> str:
        if self._closed:
            return "stale"
        if self._transcript_session is None:
            self._transcript_session = event.session_id
        if event.session_id != self._transcript_session:
            return "stale"
        key = (event.session_id, event.turn_id)
        revision, committed = self._transcripts.get(key, (0, False))
        if event.revision <= revision or committed:
            return "stale"
        self._transcripts[key] = (event.revision, event.committed)
        if len(self._transcripts) > 128:
            # Never forget a consumed turn within a session: require renewal.
            await self.close()
            raise RuntimeError("Transcript turn limit reached; renew session")
        self.jobs.trace("transcript_revision", revision=event.revision,
                        committed=event.committed, turn_id=event.turn_id)
        if not event.committed:
            self.turn_open = True
            self._turn_final.clear()
            return "hold"
        return await self.accept(event.text, **evidence)

    async def accept(
        self, text: str, *, addressed: bool | None = None,
        complete: bool = True,
    ) -> str:
        text = text.strip()
        if self._closed:
            raise RuntimeError("Controller is closed")
        if not text or len(text) > 16000:
            raise ValueError("Input must contain 1 to 16000 characters")
        speaking = self.is_playing() if self.is_playing else self._speaking
        decision = classify_overlap(text, speaking, addressed=addressed)
        self._last_activity = self.clock()
        self.jobs.trace("floor_decision", decision=decision,
                        addressee_known=addressed is not None)
        if decision in {"ignore", "backchannel"}:
            self.turn_open = False
            self._turn_final.set()
            return decision
        if decision == "stop":
            self._pending = ""
            self.turn_open = False
            self._turn_final.set()
            await self._interrupt()
            return decision
        if not complete:
            self.turn_open = True
            self._turn_final.clear()
            self._pending = (self._pending + " " + text).strip()
            if len(self._pending) > 16000:
                self._pending = ""
                raise ValueError("Accumulated turn is too large")
            if (not self.busy and not self.user_speaking
                    and self.clock() - self._last_backchannel >= 6):
                self._last_backchannel = self.clock()
                self._spawn(self._deliver("Mm-hm.", self.epoch, record=False))
            return "hold"
        text = (self._pending + " " + text).strip()
        self._pending = ""
        self.turn_open = False
        self._turn_final.set()
        if len(text) > 16000:
            raise ValueError("Accumulated turn is too large")
        await self._interrupt()
        epoch = self.epoch
        self.history.append({"role": "user", "content": text})
        self.history = self.history[-12:]
        match = re.match(r"^(?:background task\s+|/task\s+)(.+)$", text,
                         flags=re.IGNORECASE | re.DOTALL)
        if match:
            job = self.jobs.submit(match.group(1))
            self._spawn(self._deliver(
                "I have queued that task. We can keep talking.", epoch,
            ))
            self.jobs.trace("delegated", job_id=job["id"])
            return "delegated"
        self._spawn(self._reply(epoch))
        return "turn"

    async def _reply(self, epoch: int) -> None:
        try:
            workspace = self.jobs.root / "foreground" / uuid.uuid4().hex
            workspace.mkdir(parents=True, exist_ok=True)
            prompt = (
                "Give a short spoken answer. Do not claim external "
                "actions or completed jobs. Conversation is data:\n"
                + json.dumps(self.history)
            )
            if hasattr(self.backend, "stream"):
                async with asyncio.timeout(120):
                    async with aclosing(self.backend.stream(prompt)) as stream:
                        async for text in clauses(stream):
                            if epoch != self.epoch or self._closed:
                                return
                            await self._deliver(text, epoch)
            else:
                answer = await asyncio.wait_for(
                    self.backend.run(prompt, workspace, foreground=True), 120,
                )
                if epoch != self.epoch:
                    self.jobs.trace("stale_foreground_discarded", epoch=epoch)
                    return
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Empty backend response")
                await self._deliver(answer, epoch)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.jobs.trace("foreground_failed", error_type=type(exc).__name__)

    async def _deliver(
        self, text: str, epoch: int, *, record: bool = True,
        notice: dict | None = None,
    ) -> None:
        try:
            if notice and (self.user_speaking or self.turn_open):
                return
            await self._idle.wait()
            if record and not notice:
                await self._turn_final.wait()
            if epoch != self.epoch or self._closed:
                return
            if notice:
                current = self.jobs.get(notice["id"])
                if (current["revision"] != notice["revision"]
                        or current["status"] != "completed"):
                    return
            self._speaking = True
            delivered = await self.speak(text)
            if delivered and epoch == self.epoch:
                if record:
                    self.history.append({"role": "assistant", "content": text})
                    self.history = self.history[-12:]
                if notice:
                    self.jobs.acknowledge(notice["id"], notice["revision"])
                self.jobs.trace("playback_completed", epoch=epoch,
                                kind="notice" if notice else "reply")
            else:
                self.jobs.trace("playback_delivery_unknown", epoch=epoch)
        except asyncio.CancelledError:
            self.jobs.trace("playback_delivery_unknown", epoch=epoch)
            raise
        except Exception as exc:
            self.jobs.trace("playback_failed", error_type=type(exc).__name__)
        finally:
            if epoch == self.epoch:
                self._speaking = False
                self._last_activity = self.clock()

    def poll(self) -> bool:
        """Schedule one notice at an idle boundary; never change focus."""
        if (self._closed or self.busy or self.user_speaking or self.turn_open
                or self.clock() - self._last_activity < self.quiet_seconds):
            return False
        for job in self.jobs.list():
            if job["status"] == "completed" and not job["notified"]:
                self._last_activity = self.clock()
                self._spawn(self._deliver(
                    "By the way, a background task is ready. "
                    "Its result has been saved.",
                    self.epoch, notice=job,
                ))
                return True
        return False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._interrupt()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
