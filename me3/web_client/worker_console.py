"""Read-only, bounded view of settled or streaming output for one worker revision."""

import asyncio
from collections import OrderedDict
import json

from aiohttp import web


class WorkerDrafts:
    def __init__(self, max_jobs=20, max_chars=65536):
        self.max_jobs = max_jobs
        self.max_chars = max_chars
        self.entries = OrderedDict()

    def append(self, job, revision, text):
        key = job, revision
        end, tail = self.entries.get(key, (0, ""))
        self.entries[key] = end + len(text), (tail + text)[-self.max_chars:]
        self.entries.move_to_end(key)
        if len(self.entries) > self.max_jobs:
            self.entries.popitem(last=False)

    def read(self, job, revision, offset):
        entry = self.entries.get((job, revision))
        if entry is None:
            return None
        end, tail = entry
        first = end - len(tail)
        start = max(first, min(end, offset))
        return {"start": start, "end": end, "text": tail[start-first:]}


async def stream_output(request, jobs, drafts, closing):
    job_id = request.match_info["id"]
    try:
        job = jobs.get(job_id)
    except KeyError:
        raise web.HTTPNotFound(text="Job unavailable") from None
    try:
        revision = int(request.query["revision"])
        offset = max(0, int(request.headers.get("Last-Event-ID", 0)))
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(text="Invalid revision or stream position") from None

    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-store",
    })
    await response.prepare(request)
    previous = None
    try:
        while not closing() and request.transport and not request.transport.is_closing():
            status = job["status"] if job["revision"] == revision else "superseded"
            terminal = status not in {"queued", "running", "cancelling"}
            chunk = drafts.read(job_id, revision, offset)
            source = "Worker output"
            if status == "completed" and chunk is None:
                try:
                    saved = jobs.result(job_id, expected_revision=revision)
                    chunk = {"start": 0, "end": min(len(saved), drafts.max_chars),
                             "text": saved[:drafts.max_chars]}
                    source = "Saved result" if len(saved) <= drafts.max_chars else "Saved result (excerpt)"
                except (OSError, ValueError):
                    source = "Saved result unavailable"
            if status != previous or (chunk and chunk["end"] != offset) or terminal:
                data = dict(status=status, source=source, done=terminal,
                            error=job.get("error") if status == "failed" else None)
                if chunk:
                    data.update(chunk)
                    offset = chunk["end"]
                await asyncio.wait_for(response.write(
                    f"id: {offset}\ndata: {json.dumps(data)}\n\n".encode()
                ), 3)
            if terminal:
                break
            previous = status
            await asyncio.sleep(0.2)
            job = jobs.get(job_id)
    except (ConnectionError, TimeoutError):
        pass
    return response
