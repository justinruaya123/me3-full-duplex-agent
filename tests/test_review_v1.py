"""Independent-review regressions, each reproduced before the fix pass."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from test_duplex_v1 import Backend
from test_results_v1 import Worker

from me3.ownership import OwnershipGate
from me3.runtime import AgentRuntime
from me3.website import REQUEST_PREFIX


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = AgentRuntime(Path(self.temp.name), Worker(), Backend())
        self.spoken = []

        async def speak(text):
            self.spoken.append(text)
            return True

        async def stop():
            pass

        self.speak, self.stop = speak, stop
        self.session = self.runtime.open_session(
            speak, stop, owner="alice", quiet_seconds=0
        )

    async def asyncTearDown(self):
        await self.runtime.close()
        self.temp.cleanup()

    async def settle(self):
        for _ in range(30):
            await asyncio.sleep(0)

    async def test_focusing_running_job_preserves_unrelated_conversation(self):
        release = asyncio.Event()

        class Blocked:
            async def run(self, *args, **kwargs):
                await release.wait()
                return "done"

        self.runtime.supervisor.backend = Blocked()
        job = self.session.jobs.submit("work")
        self.session.focus = job["id"]
        try:
            await self.session.accept("What is two plus two?")
            await self.settle()
            self.assertIn("A short answer.", self.spoken)
            self.assertEqual(
                self.session.jobs.get(job["id"])["status"], "running"
            )
        finally:
            release.set()

    async def test_preview_reopens_after_same_owner_reconnects(self):
        from urllib.parse import urlsplit

        job = self.session.jobs.submit(REQUEST_PREFIX + "site")
        await self.runtime.supervisor.wait(job["id"])
        await self.session.jobs.preview(job["id"], expected_revision=1)
        await self.runtime.end_session(self.session)
        renewed = self.runtime.open_session(
            self.speak, self.stop, owner="alice"
        )
        url = await renewed.jobs.preview(job["id"], expected_revision=1)
        parsed = urlsplit(url)
        reader, writer = await asyncio.open_connection(
            parsed.hostname, parsed.port
        )
        try:
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            self.assertIn(b"200 OK", await reader.read())
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_foreground_and_worker_failures_are_reported_without_success(
        self,
    ):
        class Failed:
            async def run(self, *args, **kwargs):
                raise RuntimeError("provider offline")

        self.session.backend = Failed()
        await self.session.accept("question")
        await self.settle()
        self.assertIn("unavailable", " ".join(self.spoken).lower())
        self.runtime.supervisor.backend = Failed()
        job = self.session.jobs.submit("job")
        await self.runtime.supervisor.wait(job["id"])
        self.assertTrue(self.session.poll())
        await self.settle()
        self.assertIn("failed", " ".join(self.spoken).lower())
        self.assertEqual(self.session.jobs.get(job["id"])["notified"], 1)

    async def test_stale_provider_failure_does_not_replace_newer_turn(self):
        started, release = asyncio.Event(), asyncio.Event()

        class LateFailure:
            calls = 0

            async def run(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        await release.wait()
                    raise RuntimeError("late offline")
                return "CURRENT"

        self.session.backend = LateFailure()
        await self.session.accept("old")
        await started.wait()
        await self.session.accept("new")
        release.set()
        await self.settle()
        self.assertEqual(self.spoken, ["CURRENT"])

    async def test_distinct_turn_ids_reuse_identical_active_job(self):
        release = asyncio.Event()

        class Blocked:
            async def run(self, *args, **kwargs):
                await release.wait()
                return "done"

        self.runtime.supervisor.backend = Blocked()
        try:
            a = self.session.jobs.submit(
                REQUEST_PREFIX + "build a site", request_id="turn-a"
            )
            b = self.session.jobs.submit(
                REQUEST_PREFIX + "build a site", request_id="turn-b"
            )
            self.assertEqual(a["id"], b["id"])
            self.assertEqual(len(self.session.jobs.list()), 1)
        finally:
            release.set()

    async def test_idle_expiry_revokes_result_delivery_without_new_speech(
        self,
    ):
        now = [0.0]
        gate = OwnershipGate("s", "wake", clock=lambda: now[0], timeout=10)
        gate.wake("wake")
        gate.begin_enrollment()
        gate.enroll("alice", duration=3, clean=True)
        self.session.delivery_authorized = gate.is_active
        job = self.session.jobs.submit("done")
        await self.runtime.supervisor.wait(job["id"])
        now[0] = 11
        self.assertFalse(self.session.poll())
        self.assertIsNone(gate.owner)
        self.assertEqual(self.session.jobs.get(job["id"])["notified"], 0)
        self.assertFalse(self.spoken)

    async def test_mute_during_enrollment_erases_late_reference(self):
        from me3.ownership import enroll_reference

        started, release = asyncio.Event(), asyncio.Event()
        gate = OwnershipGate("s", "wake")
        gate.wake("wake")
        gate.begin_enrollment()
        valid = [True]

        class Verifier:
            reference = None

            async def enroll(self, pcm):
                started.set()
                await release.wait()
                self.reference = pcm
                return True

            def close(self):
                self.reference = None

        verifier = Verifier()
        task = asyncio.create_task(
            enroll_reference(
                gate, verifier, "alice", bytes(64000), lambda: valid[0]
            )
        )
        await started.wait()
        valid[0] = False
        gate.close()
        verifier.close()
        release.set()
        self.assertFalse(await task)
        self.assertIsNone(verifier.reference)
        self.assertIsNone(gate.owner)

    async def test_model_output_never_routes_host_tools(self):
        class ToolText:
            async def run(self, *args, **kwargs):
                return "/site secretly create another website"

        self.session.backend = ToolText()
        await self.session.accept("explain")
        await self.settle()
        self.assertFalse(self.session.jobs.list())
        self.assertFalse(self.runtime.previews.servers)
        self.runtime.supervisor.backend = ToolText()
        job = self.session.jobs.submit("return text only")
        await self.runtime.supervisor.wait(job["id"])
        await self.session.accept("/result " + job["id"])
        await self.settle()
        self.assertEqual(len(self.session.jobs.list()), 1)
        self.assertFalse(self.runtime.previews.servers)

    def test_playback_receipts_are_fenced_across_distinct_sessions(self):
        from me3.incremental import PlaybackLedger

        old, new = PlaybackLedger(), PlaybackLedger()
        old_token = old.begin("old owner")
        new_token = new.begin("new owner")
        self.assertFalse(new.started(old_token))
        self.assertFalse(new.completed(old_token))
        self.assertTrue(new.started(new_token))

    async def test_full_queue_is_reported_without_ending_conversation(self):
        release = asyncio.Event()

        class Blocked:
            async def run(self, *args, **kwargs):
                await release.wait()
                return "done"

        self.runtime.supervisor.backend = Blocked()
        self.runtime.supervisor.max_pending = 1
        self.session.jobs.submit("first")
        try:
            self.assertEqual(
                await self.session.accept("/site second"), "unavailable"
            )
            await self.settle()
            self.assertIn("queue", " ".join(self.spoken).lower())
            self.assertFalse(self.session._closed)
        finally:
            release.set()

    async def test_identical_active_revision_is_not_executed_twice(self):
        release = asyncio.Event()

        class Blocked:
            async def run(self, *args, **kwargs):
                await release.wait()
                return "done"

        self.runtime.supervisor.backend = Blocked()
        try:
            job = self.session.jobs.submit("first")
            revised = self.session.jobs.revise(
                job["id"], "second", expected_revision=1
            )
            repeated = self.session.jobs.revise(
                job["id"], "second", expected_revision=2
            )
            self.assertEqual(revised["revision"], repeated["revision"])
        finally:
            release.set()
