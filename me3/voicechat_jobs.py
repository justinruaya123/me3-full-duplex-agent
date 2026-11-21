"""Pi voice plugin's session-scoped stdio bridge to the ME3 job supervisor."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from me3.core import Supervisor, checked_prompt
from me3.harnesses import JsonProcessBackend
from me3.jobs import OwnedJobs
from me3.portfolio import PORTFOLIO_PREFIX
from me3.website import REQUEST_PREFIX, WebsiteWorker, prepare_website


SUBAGENT_PREFIX = "ME3_SUBAGENT_V1\n"


class VoiceJobs:
    def __init__(self, root, backend, notify, *, site_backend=None, draft_only=False):
        self.draft_only = draft_only
        self.supervisor = Supervisor(
            root, WebsiteWorker(backend, site_backend=site_backend), workers=1, max_pending=5, timeout=600,
            prepare_result=self.prepare,
        )
        self.jobs = OwnedJobs(self.supervisor, "local-operator", root.name)
        with self.supervisor.db as db:
            db.execute("""CREATE TABLE IF NOT EXISTS voice_receipts (
                job TEXT, revision INTEGER, follow_up INTEGER NOT NULL DEFAULT 0,
                cue_claimed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job,revision))""")
        self.notify = notify
        self.watches = {}

    async def prepare(self, text, workspace, current):
        if self.jobs.get(workspace.parent.name)["kind"] == "website":
            return await prepare_website(text, workspace, current)
        return text

    def submit(self, kind, brief, key, *, follow_up=False):
        brief = checked_prompt(brief)
        if self.draft_only and kind != "draft":
            raise ValueError("Spoken replay accepts only text drafts")
        if kind not in {"website", "portfolio", "draft", "subagent"} or not key or brief.startswith((REQUEST_PREFIX, PORTFOLIO_PREFIX)):
            raise ValueError("Invalid delegated task")
        if (kind == "subagent") != brief.startswith(SUBAGENT_PREFIX):
            raise ValueError("Invalid subagent brief")
        if kind == "subagent":
            assignment = json.loads(brief[len(SUBAGENT_PREFIX):])
            if not isinstance(assignment, dict) or assignment.get("agent") not in {"planner", "reviewer", "writer"}:
                raise ValueError("Unknown subagent role")
        prompt = REQUEST_PREFIX + brief if kind == "website" else brief
        if kind == "portfolio":
            prompt = REQUEST_PREFIX + PORTFOLIO_PREFIX + brief
        job = self.jobs.submit(prompt, request_id=kind + "/" + key)
        return self._track(job, follow_up)

    def revise(self, job_id, revision, instruction):
        current = self.jobs.get(job_id)
        instruction = checked_prompt(instruction)
        if current["prompt"].startswith(REQUEST_PREFIX + PORTFOLIO_PREFIX):
            raise ValueError("Portfolio content changes require a new public fact selection")
        if (type(revision) is int and current["revision"] in {revision, revision + 1}
                and current["prompt"].endswith("\nOwner change:\n" + instruction)):
            return self.status(job_id)
        follow_up = self.status(job_id)["follow_up"]
        job = self.jobs.revise(job_id, instruction, expected_revision=revision)
        return self._track(job, follow_up)

    def _track(self, job, follow_up):
        job_id = job["id"]
        with self.supervisor.db as db:
            db.execute("""INSERT INTO voice_receipts(job,revision,follow_up) VALUES (?,?,?)
                        ON CONFLICT(job,revision) DO UPDATE
                        SET follow_up=MAX(follow_up,excluded.follow_up)""",
                       (job_id, job["revision"], int(follow_up is True)))
        if job["status"] in {"queued", "running"} and job_id not in self.watches:
            self.watches[job_id] = asyncio.create_task(self._watch(job_id))
        return self.status(job_id)

    def claim_cue(self, job_id, revision):
        job = self.jobs.get(job_id)
        if job["revision"] != revision or job["status"] not in {"queued", "running"}:
            return False
        with self.supervisor.db as db:
            return db.execute("""UPDATE voice_receipts SET cue_claimed=1
                              WHERE job=? AND revision=? AND cue_claimed=0""",
                              (job_id, revision)).rowcount == 1

    def notices(self):
        rows = self.supervisor.db.execute("""
            SELECT j.id FROM jobs j JOIN voice_receipts r
            ON r.job=j.id AND r.revision=j.revision JOIN job_owners o ON o.job_id=j.id
            WHERE o.owner=? AND o.session_id=? AND r.follow_up=1 AND j.notified=0
            AND j.status IN ('completed','failed','interrupted') ORDER BY j.created LIMIT 1
        """, (self.jobs.owner, self.jobs.session_id))
        return [self.status(row[0]) for row in rows]

    async def _watch(self, job_id):
        previous = None
        try:
            while True:
                snapshot = self.status(job_id, for_display=True)
                if snapshot != previous:
                    self.notify(snapshot)
                    previous = snapshot
                if snapshot["status"] not in {"queued", "running", "cancelling"}:
                    return
                await asyncio.sleep(.5)
        finally:
            self.watches.pop(job_id, None)

    def status(self, job_id=None, *, for_display=False):
        if not job_id:
            recent = self.jobs.list()
            if not recent:
                return {"status": "empty"}
            job_id = recent[-1]["id"]
        job = self.jobs.get(job_id)
        result = {k: job[k] for k in ("id", "status", "kind", "revision")}
        if job["kind"] == "draft" and job["prompt"].startswith(SUBAGENT_PREFIX):
            try:
                assignment = json.loads(job["prompt"][len(SUBAGENT_PREFIX):].partition("\nOwner change:\n")[0])
                if isinstance(assignment, dict) and assignment.get("agent") in {"planner", "reviewer", "writer"}:
                    result["agent"] = assignment["agent"]
            except ValueError:
                pass  # Legacy free-form drafts could start with this marker.
        row = self.supervisor.db.execute(
            "SELECT follow_up FROM voice_receipts WHERE job=? AND revision=?",
            (job_id, job["revision"])).fetchone()
        result["follow_up"] = bool(row and row[0] and not job["notified"])
        if job["status"] == "running" and (for_display or job["kind"] == "draft"):
            revision = self.supervisor.root / "jobs" / job_id / f"revision-{job['revision']}"
            try:
                limit = 8192 if for_display else 550
                result["preview"] = (revision / "worker-preview.txt").read_text()[-limit:]
            except FileNotFoundError:
                pass
        if job["status"] == "failed":
            result["error"] = job["error"]
        if job["status"] == "completed":
            artifact = self.supervisor.root / job["artifact"]
            result.update(text=self.jobs.result(job_id)[:12000], artifact=str(artifact))
            if job["kind"] == "website":
                result.update(index=str(artifact.parent / "site/index.html"),
                              receipt=str(artifact.parent / "verification.json"))
                archive = artifact.parent / "website.zip"
                if archive.is_file():
                    result["archive"] = str(archive)
        return result

    async def close(self):
        watches = list(self.watches.values())
        for task in watches:
            task.cancel()
        await asyncio.gather(*watches, return_exceptions=True)
        await self.supervisor.close()


def emit(record):
    print(json.dumps(record), flush=True)


async def run(session, replay_dir=None):
    root = Path(__file__).resolve().parents[1]
    state = replay_dir if replay_dir is not None else root / ".local/voice-worker"
    state.mkdir(mode=0o700, parents=True, exist_ok=replay_dir is None)
    agent = state / "agent"
    agent.mkdir(mode=0o700, parents=True, exist_ok=True)
    def backend(*args):
        return JsonProcessBackend(
            (os.environ["ME3_NODE"], str(root / "integrations/voicechat/worker.mjs"), *args),
            env={"PI_CODING_AGENT_DIR": str(agent)}, timeout=600, max_bytes=2_097_152,
        )

    chat = hashlib.sha256(session.encode()).hexdigest()
    jobs = VoiceJobs(state / "chats" / chat, backend(), lambda job: emit({"event": job}),
                     site_backend=backend("--website"), draft_only=replay_dir is not None)
    try:
        while line := await asyncio.to_thread(sys.stdin.buffer.readline, 131073):
            if len(line) > 131072:
                raise ValueError("Oversized control request")
            req = json.loads(line)
            try:
                if req["op"] == "submit":
                    result = jobs.submit(req["kind"], req["brief"], req["key"],
                                         follow_up=req.get("follow_up") is True)
                elif req["op"] == "revise":
                    result = jobs.revise(req["job"], req["revision"], req["instruction"])
                elif req["op"] == "claim_cue":
                    result = jobs.claim_cue(req["job"], req["revision"])
                elif req["op"] == "notices":
                    result = jobs.notices()
                elif req["op"] == "delivered":
                    result = jobs.jobs.acknowledge(req["job"], req["revision"])
                elif req["op"] == "status":
                    result = jobs.status(req.get("job"))
                else:
                    raise ValueError("Unknown job operation")
                emit({"id": req["id"], "result": result})
            except (KeyError, ValueError, RuntimeError) as exc:
                emit({"id": req["id"], "error": str(exc)})
    finally:
        await jobs.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("session")
    parser.add_argument("--replay-drafts", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.session, args.replay_drafts))
