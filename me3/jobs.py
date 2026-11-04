"""Durable owner bindings and revision-checked commands over the legacy store."""

from __future__ import annotations

from me3.core import checked_prompt
from me3.website import REQUEST_PREFIX


class OwnedJobs:
    def __init__(
        self,
        supervisor,
        owner: str | None,
        session_id: str,
        *,
        previews=None,
        changed=None,
    ) -> None:
        self.supervisor, self.owner = supervisor, owner
        self.session_id, self.root = session_id, supervisor.root
        self.previews, self.changed = previews, changed
        self.authorized = lambda: True
        with supervisor.db:
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_owners (
                job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                session_id TEXT NOT NULL, kind TEXT NOT NULL)""")
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_requests (
                owner TEXT NOT NULL, request_id TEXT NOT NULL,
                job_id TEXT NOT NULL, PRIMARY KEY(owner, request_id))""")

    def _authorize(self) -> None:
        if not self.owner or not self.authorized():
            raise PermissionError("Session no longer authorizes actions")

    def submit(self, prompt: str, *, request_id: str | None = None) -> dict:
        self._authorize()
        prompt = checked_prompt(prompt)
        if request_id:
            row = self.supervisor.db.execute(
                "SELECT job_id FROM job_requests WHERE owner=? AND request_id=?",
                (self.owner, request_id),
            ).fetchone()
            if row:
                return self.get(row["job_id"])
        for active in self.list():
            if (
                active["status"] in {"queued", "running"}
                and active["prompt"] == prompt
            ):
                if request_id:
                    with self.supervisor.db:
                        self.supervisor.db.execute(
                            "INSERT INTO job_requests VALUES (?,?,?)",
                            (self.owner, request_id, active["id"]),
                        )
                return active
        job = self.supervisor.submit(prompt)
        with self.supervisor.db:
            self.supervisor.db.execute(
                "INSERT INTO job_owners VALUES (?,?,?,?)",
                (
                    job["id"],
                    self.owner,
                    self.session_id,
                    "website"
                    if prompt.startswith(REQUEST_PREFIX)
                    else "draft",
                ),
            )
            if request_id:
                self.supervisor.db.execute(
                    "INSERT INTO job_requests VALUES (?,?,?)",
                    (self.owner, request_id, job["id"]),
                )
        return self.get(job["id"])

    def get(self, job_id: str) -> dict:
        row = self.supervisor.db.execute(
            "SELECT * FROM job_owners WHERE job_id=? AND owner=?",
            (job_id, self.owner),
        ).fetchone()
        if row is None:
            raise KeyError("Unknown job for this owner")
        return {**self.supervisor.get(job_id), **dict(row)}

    def list(self) -> list[dict]:
        return [
            self.get(row["job_id"])
            for row in self.supervisor.db.execute(
                "SELECT job_id FROM job_owners WHERE owner=? ORDER BY rowid",
                (self.owner,),
            )
        ]

    def _revision(self, job_id: str, revision: int) -> dict:
        job = self.get(job_id)
        if job["revision"] != revision:
            raise ValueError("Stale job revision")
        return job

    def result(
        self, job_id: str, *, expected_revision: int | None = None
    ) -> str:
        job = self.get(job_id)
        if expected_revision is not None:
            self._revision(job_id, expected_revision)
        return self.supervisor.result(job["id"])

    def _invalidate(self, job_id: str) -> None:
        if self.previews:
            self.previews.stop(job_id)
        if self.changed:
            self.changed(job_id)

    def revise(
        self, job_id: str, prompt: str, *, expected_revision: int
    ) -> dict:
        self._authorize()
        job = self._revision(job_id, expected_revision)
        if job["kind"] == "website" and not prompt.startswith(REQUEST_PREFIX):
            prompt = REQUEST_PREFIX + prompt
        prompt = checked_prompt(prompt)
        if job["status"] in {"queued", "running"} and job["prompt"] == prompt:
            return job
        result = self.supervisor.update(job_id, prompt)
        self._invalidate(job_id)
        return {**result, **{key: job[key] for key in ("owner", "kind")}}

    def cancel(self, job_id: str, *, expected_revision: int) -> dict:
        self._authorize()
        self._revision(job_id, expected_revision)
        result = self.supervisor.cancel(job_id)
        self._invalidate(job_id)
        return result

    async def preview(self, job_id: str, *, expected_revision: int) -> str:
        self._authorize()
        job = self._revision(job_id, expected_revision)
        if job["kind"] != "website" or self.previews is None:
            raise ValueError("No website preview is available")
        return await self.previews.start(
            job,
            self.root,
            lambda: (
                self.authorized()
                and self.get(job_id)["revision"] == expected_revision
                and self.get(job_id)["status"] == "completed"
            ),
            session_id=self.session_id,
        )

    def acknowledge(self, job_id: str, revision: int) -> None:
        self._revision(job_id, revision)
        with self.supervisor.db:
            self.supervisor.db.execute(
                "UPDATE jobs SET notified=1 WHERE id=? AND revision=? "
                "AND status IN ('completed','failed','interrupted')",
                (job_id, revision),
            )

    def trace(self, event: str, **fields) -> None:
        self.supervisor.trace(event, session_id=self.session_id, **fields)
