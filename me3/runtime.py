"""Long-lived job ownership, independent of voice transport/session lifetime."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from me3.core import Supervisor
from me3.duplex import DuplexController, SupervisorJobs
from me3.website import WebsiteWorker, prepare_website
from me3.jobs import OwnedJobs
from me3.preview import PreviewManager


class AgentRuntime:
    def __init__(self, root: Path, worker, foreground) -> None:
        self.worker = WebsiteWorker(worker)
        self.supervisor = Supervisor(
            root, self.worker, timeout=600, prepare_result=prepare_website,
        )
        self.foreground = foreground
        self.sessions: set[DuplexController] = set()
        self.previews = PreviewManager()
        self.closed = False

    def open_session(self, speak, stop, *, owner=None, **options) -> DuplexController:
        if self.closed:
            raise RuntimeError('Runtime is closed')
        session = DuplexController(
            OwnedJobs(
                self.supervisor, owner, uuid.uuid4().hex,
                previews=self.previews, changed=self._job_changed,
            ), self.foreground,
            speak, stop, **options,
        )
        session.jobs.authorized = lambda: not session._closed
        self.sessions.add(session)
        return session

    def _job_changed(self, job_id: str) -> None:
        for session in self.sessions:
            session.invalidate_job(job_id)

    async def end_session(self, session: DuplexController) -> None:
        await session.close()
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
