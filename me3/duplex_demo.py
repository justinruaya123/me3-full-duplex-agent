"""Deterministic in-memory control demo. No audio or inference benchmark."""

import asyncio
import json
import tempfile
from pathlib import Path

from me3.duplex import DuplexController


class DemoJobs:
    def __init__(self, root):
        self.root, self.items, self.events = root, {}, []

    def submit(self, prompt):
        job = dict(id=str(len(self.items) + 1), prompt=prompt, revision=1,
                   status="running", notified=0)
        self.items[job["id"]] = job
        return dict(job)

    def list(self):
        return [dict(job) for job in self.items.values()]

    def get(self, job_id):
        return dict(self.items[job_id])

    def acknowledge(self, job_id, revision):
        job = self.items[job_id]
        if job["revision"] == revision and job["status"] == "completed":
            job["notified"] = 1

    def trace(self, event, **fields):
        self.events.append({"event": event, **fields})


class DemoBackend:
    async def run(self, prompt, workspace, *, foreground=False):
        return "SIMULATOR: foreground response while a job remains active."


async def demo() -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        jobs = DemoJobs(Path(temporary))
        speaking = asyncio.Event()
        release = asyncio.Event()
        spoken = []

        async def speak(text):
            spoken.append(text)
            speaking.set()
            await release.wait()
            return True

        async def stop():
            pass

        controller = DuplexController(
            jobs, DemoBackend(), speak, stop, quiet_seconds=0,
        )
        try:
            job = jobs.submit("Draft an explanation")
            await controller.accept("Explain attention")
            await speaking.wait()
            acknowledgment = await controller.accept("mm-hmm")
            still_speaking = controller.busy
            await controller.accept("stop talking")
            survived = jobs.get(job["id"])["status"] == "running"
            release.set()
            jobs.items[job["id"]]["status"] = "completed"
            controller.user_started()
            deferred = not controller.poll()
            controller.user_stopped()
            await controller.accept("stop talking")
            controller.poll()
            for _ in range(10):
                await asyncio.sleep(0)
            result = {
                "mode": "SIMULATOR, in-memory; not acoustic qualification",
                "backchannel_preserved_speech": (
                    acknowledgment == "backchannel" and still_speaking
                ),
                "speech_stop_preserved_job": survived,
                "notice_deferred_during_user_turn": deferred,
                "notice_acknowledged_after_delivery": bool(
                    jobs.get(job["id"])["notified"]
                ),
                "focus_unchanged": controller.focus is None,
                "spoken": spoken,
            }
            assert all(value for value in result.values())
            return result
        finally:
            await controller.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(demo()), indent=2))
