"""Long-lived job ownership, independent of voice transport/session lifetime."""
from __future__ import annotations

from pathlib import Path

from me3.core import Supervisor
from me3.duplex import DuplexController, SupervisorJobs
from me3.website import WebsiteWorker, prepare_website


class AgentRuntime:
    def __init__(self, root: Path, worker, foreground) -> None:
        self.worker = WebsiteWorker(worker)
        self.supervisor = Supervisor(
            root, self.worker, timeout=600, prepare_result=prepare_website,
        )
        self.foreground = foreground
        self.sessions: set[DuplexController] = set()
        self.closed = False

    def open_session(self, speak, stop, **options) -> DuplexController:
        if self.closed:
            raise RuntimeError('Runtime is closed')
        session = DuplexController(
            SupervisorJobs(self.supervisor), self.foreground,
            speak, stop, **options,
        )
        self.sessions.add(session)
        return session

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
        await self.supervisor.close()
        await self.worker.close()
