"""Deterministic orchestration tests; no models, audio hardware or network."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from me3.core import Controller, Supervisor


class GateBackend:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def run(self, prompt, workspace, *, foreground=False):
        self.calls.append((prompt, workspace, foreground))
        if foreground:
            return "foreground reply"
        self.started.set()
        await self.release.wait()
        return "worker result: " + prompt


class CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backend = GateBackend()
        self.supervisor = Supervisor(self.root, self.backend)
        self.controller = Controller(self.supervisor, self.backend)

    async def asyncTearDown(self):
        await self.controller.close()
        await self.supervisor.close()
        self.temp.cleanup()

    async def complete(self, job_id):
        self.backend.release.set()
        await self.supervisor.wait(job_id)
        return self.supervisor.get(job_id)

    async def test_foreground_works_while_worker_is_blocked(self):
        job = self.supervisor.submit("write a report")
        await self.backend.started.wait()
        answer = await asyncio.wait_for(self.controller.ask("hello"), 1)
        self.assertEqual(answer, "foreground reply")
        self.assertEqual(self.supervisor.get(job["id"])["status"], "running")
        self.assertNotEqual(self.backend.calls[0][1], self.backend.calls[1][1])

    async def test_stop_speech_does_not_cancel_job(self):
        job = self.supervisor.submit("report")
        await self.backend.started.wait()
        speaking = asyncio.Event()

        async def speaker(text):
            speaking.set()
            await asyncio.Event().wait()

        self.controller.speaker = speaker
        response = asyncio.create_task(self.controller.ask("explain"))
        await speaking.wait()
        self.controller.interrupt()
        await asyncio.gather(response, return_exceptions=True)
        self.assertEqual(self.supervisor.get(job["id"])["status"], "running")
        self.assertFalse(any(m["content"] == "foreground reply"
                             for m in self.controller.history))
        self.assertEqual(
            (await self.complete(job["id"]))["status"],
            "completed",
        )

    async def test_no_notice_while_user_speaks_or_focus_change(self):
        job = self.supervisor.submit("report")
        await self.complete(job["id"])
        self.controller.user_speaking = True
        self.assertEqual(self.controller.notices(), [])
        self.controller.user_speaking = False
        self.assertEqual(self.controller.notices()[0]["id"], job["id"])
        self.assertIsNone(self.controller.focus)
        self.assertEqual(self.controller.notices(), [])

    async def test_cancel_before_worker_starts(self):
        job = self.supervisor.submit("report")
        self.supervisor.cancel(job["id"])
        await self.supervisor.wait(job["id"])
        self.assertEqual(self.supervisor.get(job["id"])["status"], "cancelled")
        self.assertEqual(self.controller.notices(), [])

    async def test_update_uses_new_revision_and_artifact(self):
        job = self.supervisor.submit("old")
        await self.backend.started.wait()
        updated = self.supervisor.update(job["id"], "new")
        result = await self.complete(job["id"])
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self.supervisor.result(job["id"]),
            "worker result: new",
        )
        self.assertIn("revision-2", result["artifact"])

    async def test_recovery_preserves_result_and_does_not_auto_resume(self):
        complete = self.supervisor.submit("done")
        await self.complete(complete["id"])
        self.backend.release.clear()
        pending = self.supervisor.submit("unfinished")
        await asyncio.sleep(0)
        await self.supervisor.close()
        self.supervisor = Supervisor(self.root, self.backend)
        self.controller.supervisor = self.supervisor
        self.assertEqual(
            self.supervisor.get(pending["id"])["status"],
            "interrupted",
        )
        self.assertEqual(
            self.supervisor.result(complete["id"]),
            "worker result: done",
        )

    async def test_second_supervisor_is_rejected(self):
        with self.assertRaises(RuntimeError):
            Supervisor(self.root, self.backend)

    async def test_unknown_id_and_empty_prompt_are_rejected(self):
        with self.assertRaises(KeyError):
            self.supervisor.get("../other")
        with self.assertRaises(ValueError):
            self.supervisor.submit("   ")

    async def test_focus_is_explicit_and_result_is_bounded_context(self):
        job = self.supervisor.submit("report")
        await self.complete(job["id"])
        self.controller.set_focus(job["id"])
        await self.controller.ask("summarize it")
        self.assertIn("worker result: report", self.backend.calls[-1][0])

    async def test_backend_failure_is_not_completion(self):
        class Broken:
            async def run(self, *args, **kwargs):
                raise RuntimeError("provider failed")

        self.supervisor.backend = Broken()
        job = self.supervisor.submit("report")
        await self.supervisor.wait(job["id"])
        self.assertEqual(self.supervisor.get(job["id"])["status"], "failed")
        self.assertEqual(self.controller.notices(), [])

    async def test_cancel_status_waits_for_worker_cleanup(self):
        job = self.supervisor.submit("report")
        await self.backend.started.wait()
        requested = self.supervisor.cancel(job["id"])
        self.assertEqual(requested["status"], "cancelling")
        await self.supervisor.wait(job["id"])
        self.assertEqual(self.supervisor.get(job["id"])["status"], "cancelled")

    async def test_late_old_revision_cannot_replace_new_result(self):
        started = asyncio.Event()

        class LateBackend:
            async def run(self, prompt, workspace, *, foreground=False):
                if prompt == "old":
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        return "stale result despite cancellation"
                return "new result"

        self.supervisor.backend = LateBackend()
        job = self.supervisor.submit("old")
        await started.wait()
        self.supervisor.update(job["id"], "new")
        await self.supervisor.wait(job["id"])
        self.assertEqual(self.supervisor.result(job["id"]), "new result")
        self.assertFalse(list(self.root.glob("jobs/*/revision-1/result.md")))

    async def test_queue_is_bounded(self):
        self.supervisor.max_pending = 1
        self.supervisor.submit("one")
        with self.assertRaises(RuntimeError):
            self.supervisor.submit("two")


if __name__ == "__main__":
    unittest.main()
