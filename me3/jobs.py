"""Durable owner bindings and revision-checked job commands."""

from __future__ import annotations

import json

from me3.core import checked_prompt
from me3.website import NAMED_SITE_PREFIX, REQUEST_PREFIX


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
        self.submitted = None
        self.site_context = None
        self.on_deferred = None
        with supervisor.db:
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_owners (
                job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                session_id TEXT NOT NULL, kind TEXT NOT NULL)""")
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_requests (
                owner TEXT NOT NULL, request_id TEXT NOT NULL,
                job_id TEXT NOT NULL, PRIMARY KEY(owner, request_id))""")
            if not supervisor.db.execute("SELECT 1 FROM sqlite_master WHERE name='job_return_preferences'").fetchone():
                supervisor.db.execute("""CREATE TABLE job_return_preferences (
                    job_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    policy TEXT NOT NULL CHECK(policy IN ('ask_first','after_topic')),
                    PRIMARY KEY(job_id, revision))""")
                if supervisor.db.execute("SELECT 1 FROM sqlite_master WHERE name='job_returns'").fetchone():
                    supervisor.db.execute("""INSERT INTO job_return_preferences
                        SELECT j.id, j.revision, r.policy FROM jobs j
                        JOIN job_returns r ON r.job_id=j.id""")

            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS task_checkpoint (
                owner TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                revision INTEGER NOT NULL)""")
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS job_delivery (
                job_id TEXT NOT NULL, revision INTEGER NOT NULL,
                deferred INTEGER NOT NULL DEFAULT 0,
                notice_state TEXT NOT NULL DEFAULT 'pending',
                requested INTEGER NOT NULL DEFAULT 0,
                report_state TEXT NOT NULL DEFAULT 'pending',
                report_offset INTEGER NOT NULL DEFAULT 0,
                attempt TEXT, PRIMARY KEY(job_id, revision))""")
            supervisor.db.execute("""CREATE TABLE IF NOT EXISTS notice_clock (
                owner TEXT PRIMARY KEY, last_offer REAL NOT NULL)""")

    def _authorize(self) -> None:
        if not self.owner or not self.authorized():
            raise PermissionError("Session no longer authorizes actions")

    def _site_prompt(self, instruction: str, previous: str | None = None) -> str:
        from me3.memory import personal_design, personal_site

        raw = checked_prompt(instruction.removeprefix(REQUEST_PREFIX))
        new = REQUEST_PREFIX + raw
        named = (previous or new).startswith(NAMED_SITE_PREFIX)
        if not named and (personal_site(new) or (previous and personal_site(previous))):
            # Personal checkpoints contain design terms alone. Approved values
            # are selected again under the current owner's privacy settings.
            context = (
                self.site_context(REQUEST_PREFIX + "about me")
                if self.site_context
                else ""
            )
            public = json.loads(context)["public_approved"] if context else {}
            if not public:
                raise ValueError("Personal website needs current public-approved facts")
            prior_design = ()
            marker = REQUEST_PREFIX + "about me\nDesign: "
            if previous and previous.startswith(marker):
                prior_design = personal_design(previous[len(marker) :], {})
            changes = personal_design(new, public)
            terms = tuple(dict.fromkeys((*prior_design, *changes)))
            return (
                REQUEST_PREFIX
                + "about me"
                + ("\nDesign: " + " ".join(terms) if terms else "")
            )
        if not previous or previous == new:
            return checked_prompt(new)
        edit = "\nOwner change:\n" + raw
        if previous.endswith(edit):
            return previous
        return checked_prompt(previous + edit)

    def revision_prompt(self, job: dict, instruction: str) -> str:
        if job["kind"] == "website":
            from me3.memory import personal_site

            previous = job["prompt"]
            if (
                not personal_site(previous)
                and self.supervisor.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_context_use'"
                ).fetchone()
            ):
                # Pre-checkpoint releases could persist only the latest edit.
                # Preserve their recorded privacy classification after restart.
                row = self.supervisor.db.execute(
                    "SELECT personal FROM job_context_use WHERE job_id=? AND owner=?",
                    (job["id"], self.owner),
                ).fetchone()
                if row and row["personal"]:
                    previous = REQUEST_PREFIX + "about me"
            return self._site_prompt(instruction, previous=previous)
        edit = checked_prompt(instruction)
        previous = job["prompt"]
        suffix = "\nOwner change:\n" + edit
        if previous == edit or previous.endswith(suffix):
            return previous
        return checked_prompt(previous + suffix)

    def submit(self, prompt: str, *, request_id: str | None = None) -> dict:
        self._authorize()
        prompt = checked_prompt(prompt)
        if request_id:
            row = self.supervisor.db.execute(
                "SELECT job_id FROM job_requests "
                "WHERE owner=? AND request_id=?",
                (self.owner, request_id),
            ).fetchone()
            if row:
                return self.get(row["job_id"])
        if prompt.startswith(REQUEST_PREFIX):
            prompt = self._site_prompt(prompt)
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
        def bind(job_id: str) -> None:
            self.supervisor.db.execute(
                "INSERT INTO job_owners VALUES (?,?,?,?)",
                (job_id, self.owner, self.session_id,
                 "website" if prompt.startswith(REQUEST_PREFIX) else "draft"),
            )
            if request_id:
                self.supervisor.db.execute(
                    "INSERT INTO job_requests VALUES (?,?,?)",
                    (self.owner, request_id, job_id),
                )
            self._checkpoint(job_id, 1)

        job = self.supervisor.submit(prompt, bind=bind)
        if self.submitted:
            self.submitted(job["id"])
        return self.get(job["id"])

    def get(self, job_id: str) -> dict:
        row = self.supervisor.db.execute(
            "SELECT o.*, p.policy AS return_policy FROM job_owners o JOIN jobs j ON j.id=o.job_id "
            "LEFT JOIN job_return_preferences p ON p.job_id=j.id AND p.revision=j.revision "
            "WHERE o.job_id=? AND o.owner=?",
            (job_id, self.owner),
        ).fetchone()
        if row is None:
            raise KeyError("Unknown job for this owner")
        job = self.supervisor.get(job_id)
        delivery = self.supervisor.db.execute(
            "SELECT deferred, notice_state, requested, report_state, report_offset "
            "FROM job_delivery WHERE job_id=? AND revision=?",
            (job_id, job["revision"]),
        ).fetchone()
        fields = dict(delivery) if delivery else {
            "deferred": 0, "notice_state": "pending", "requested": 0,
            "report_state": "pending", "report_offset": 0,
        }
        # Existing jobs retain their brief-notice receipts during migration.
        if job["notified"]:
            fields["notice_state"] = "confirmed"
        return {**job, **dict(row), **fields}

    def set_return_policy(
        self, job_id: str, policy: str, *, expected_revision: int
    ) -> None:
        self._authorize()
        previous = self._revision(job_id, expected_revision)
        if policy not in {"ask_first", "after_topic"}:
            raise ValueError("Unknown result return policy")
        if previous["return_policy"] == policy and not previous["deferred"]:
            return
        with self.supervisor.db:
            self.supervisor.db.execute(
                "INSERT OR REPLACE INTO job_return_preferences VALUES (?,?,?)",
                (job_id, expected_revision, policy),
            )
            if policy == "after_topic":
                self.supervisor.db.execute("UPDATE job_delivery SET deferred=0 WHERE job_id=? AND revision=?",
                                           (job_id, expected_revision))
        if self.changed:
            self.changed(job_id)

    def list(self, *, limit: int = -1) -> list[dict]:
        ids = self.supervisor.db.execute(
            "SELECT job_id FROM job_owners WHERE owner=? ORDER BY rowid DESC LIMIT ?",
            (self.owner, limit),
        ).fetchall()
        return [self.get(row["job_id"]) for row in reversed(ids)]

    def task_digest(self, referenced_id: str | None = None) -> list[dict]:
        self._authorize()
        return [dict(row) for row in self.supervisor.db.execute(
            """SELECT j.id, j.revision, j.status, substr(j.prompt,1,240) AS prompt
               FROM job_owners o JOIN jobs j ON j.id=o.job_id
               WHERE o.owner=? ORDER BY (o.job_id=?) DESC, o.rowid DESC LIMIT 8""",
            (self.owner, referenced_id),
        )]

    def _revision(self, job_id: str, revision: int) -> dict:
        job = self.get(job_id)
        if job["revision"] != revision:
            raise ValueError("Stale job revision")
        return job

    def _checkpoint(self, job_id: str, revision: int) -> None:
        self.supervisor.db.execute(
            "INSERT OR REPLACE INTO task_checkpoint VALUES (?,?,?)",
            (self.owner, job_id, revision),
        )

    def checkpoint(self, job: dict) -> None:
        self._authorize()
        self._revision(job["id"], job["revision"])
        with self.supervisor.db:
            self._checkpoint(job["id"], job["revision"])

    def restore_checkpoint(self) -> dict | None:
        self._authorize()
        row = self.supervisor.db.execute(
            "SELECT job_id FROM task_checkpoint WHERE owner=?", (self.owner,)
        ).fetchone()
        return self.get(row["job_id"]) if row else None

    def progress(self, job: dict) -> list[str]:
        self._authorize()
        self._revision(job["id"], job["revision"])
        return [row["event"] for row in self.supervisor.db.execute(
            "SELECT event FROM job_progress WHERE job_id=? AND revision=? "
            "ORDER BY rowid", (job["id"], job["revision"]),
        )]

    def _ensure_delivery(self, job: dict) -> None:
        self._authorize()
        self._revision(job["id"], job["revision"])
        self.supervisor.db.execute(
            "INSERT OR IGNORE INTO job_delivery(job_id, revision) VALUES (?,?)",
            (job["id"], job["revision"]),
        )

    def defer(self, job: dict) -> None:
        with self.supervisor.db:
            self._ensure_delivery(job)
            self.supervisor.db.execute(
                "INSERT OR REPLACE INTO job_return_preferences VALUES (?,?,'ask_first')",
                (job["id"], job["revision"]),
            )
            self.supervisor.db.execute(
                "UPDATE job_delivery SET deferred=1 WHERE job_id=? AND revision=?",
                (job["id"], job["revision"]),
            )

        if self.on_deferred:
            self.on_deferred(job["id"])

    def notice_due(self, now: float) -> bool:
        row = self.supervisor.db.execute(
            "SELECT last_offer FROM notice_clock WHERE owner=?", (self.owner,)
        ).fetchone()
        return not row or now - row["last_offer"] >= 30

    def ready_notices(self, *, topic_closed=False) -> list[dict]:
        if not self.owner or not self.authorized():
            return []
        rows = self.supervisor.db.execute(
            """SELECT j.id FROM jobs j
               JOIN job_owners o ON o.job_id=j.id
               LEFT JOIN job_delivery d ON d.job_id=j.id AND d.revision=j.revision
               LEFT JOIN job_return_preferences p ON p.job_id=j.id AND p.revision=j.revision
               WHERE (p.policy IS NULL OR (p.policy='after_topic' AND ?))
                 AND o.owner=? AND j.status IN ('completed','failed','interrupted')
                 AND j.notified=0 AND COALESCE(d.deferred,0)=0
               ORDER BY o.rowid LIMIT 3""", (topic_closed, self.owner),
        )
        return [self.get(row["id"]) for row in rows]

    def begin_notice(self, jobs: list[dict], now: float, *, topic_closed=False) -> bool:
        with self.supervisor.db:
            if not self.notice_due(now):
                return False
            eligible = {(job["id"], job["revision"]) for job in self.ready_notices(topic_closed=topic_closed)}
            if not jobs or any((job["id"], job["revision"]) not in eligible for job in jobs):
                return False
            for job in jobs:
                self._ensure_delivery(job)
            self.supervisor.db.execute(
                "INSERT OR REPLACE INTO notice_clock VALUES (?,?)",
                (self.owner, now),
            )
            self.supervisor.db.executemany(
                "UPDATE job_delivery SET notice_state='uncertain' "
                "WHERE job_id=? AND revision=?",
                [(job["id"], job["revision"]) for job in jobs],
            )
        return True

    def request_report(self, job: dict, attempt: str) -> None:
        with self.supervisor.db:
            self._ensure_delivery(job)
            self.supervisor.db.execute(
                "UPDATE job_delivery SET deferred=1, requested=1, attempt=?, "
                "report_offset=CASE WHEN report_state='confirmed' THEN 0 "
                "ELSE report_offset END, report_state=CASE WHEN "
                "report_state='confirmed' THEN 'pending' ELSE report_state END "
                "WHERE job_id=? AND revision=?",
                (attempt, job["id"], job["revision"]),
            )

    def report_receipt(self, job: dict, attempt: str, offset: int,
                       state: str, next_offset: int) -> bool:
        self._authorize()
        self._revision(job["id"], job["revision"])
        if state not in {"uncertain", "partial", "confirmed"}:
            raise ValueError("Invalid playback receipt")
        with self.supervisor.db:
            cursor = self.supervisor.db.execute(
                "UPDATE job_delivery SET report_state=?, report_offset=? "
                "WHERE job_id=? AND revision=? AND attempt=? AND report_offset=?",
                (state, next_offset, job["id"], job["revision"], attempt, offset),
            )
            if cursor.rowcount and state == "confirmed":
                self.supervisor.db.execute(
                    "UPDATE jobs SET notified=1 WHERE id=? AND revision=?",
                    (job["id"], job["revision"]),
                )
            return cursor.rowcount == 1

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
        prompt = self.revision_prompt(job, prompt)
        if job["status"] in {"queued", "running"} and job["prompt"] == prompt:
            return job
        result = self.supervisor.update(job_id, prompt)
        self.checkpoint(result)
        self._invalidate(job_id)
        if self.submitted:
            self.submitted(job_id)
        return {**result, **{key: job[key] for key in ("owner", "kind")}}

    def cancel(self, job_id: str, *, expected_revision: int) -> dict:
        self._authorize()
        job = self._revision(job_id, expected_revision)
        if job["status"] in {"completed", "failed", "interrupted"}:
            self.defer(job)
            return self.get(job_id)
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
