"""Control-plane checks; no microphone or real inference is implied."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from me3.duplex import DuplexController, classify_overlap


class Jobs:
    def __init__(self, root):
        self.root = root
        self.items = {}
        self.events = []

    def submit(self, prompt):
        job_id = str(len(self.items) + 1)
        job = dict(id=job_id, prompt=prompt, revision=1,
                   status="running", notified=0)
        self.items[job_id] = job
        return dict(job)

    def list(self):
        return [dict(job) for job in self.items.values()]

    def get(self, job_id):
        return dict(self.items[job_id])

    def result(self, job_id):
        return "Completed draft."

    def acknowledge(self, job_id, revision):
        job = self.items[job_id]
        if job["revision"] == revision and job["status"] == "completed":
            job["notified"] = 1

    def trace(self, event, **fields):
        self.events.append((event, fields))


class Backend:
    async def run(self, prompt, workspace, *, foreground=False):
        return "A short answer."


class PolicyTests(unittest.TestCase):
    def test_acknowledgment_during_speech_keeps_floor(self):
        self.assertEqual(classify_overlap("Mm-hmm!", True), "backchannel")

    def test_idle_acknowledgment_is_a_turn(self):
        self.assertEqual(classify_overlap("yes", False), "turn")

    def test_acknowledgment_prefix_does_not_hide_command(self):
        self.assertEqual(
            classify_overlap("yes but stop talking", True), "turn",
        )

    def test_stop_must_be_entire_control_phrase(self):
        self.assertEqual(classify_overlap("stop talking", True), "stop")
        self.assertEqual(classify_overlap("explain stop codons", True), "turn")

    def test_background_classification_requires_external_evidence(self):
        self.assertEqual(
            classify_overlap("hello", True, addressed=False), "ignore",
        )
        self.assertEqual(classify_overlap("hello", True), "turn")


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = Jobs(Path(self.temp.name))
        self.spoken = []
        self.stops = 0
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.block_speech = False
        self.now = 10.0

        async def speak(text):
            self.spoken.append(text)
            self.started.set()
            if self.block_speech:
                await self.release.wait()
            return True

        async def stop():
            self.stops += 1

        self.controller = DuplexController(
            self.jobs, Backend(), speak, stop,
            clock=lambda: self.now, quiet_seconds=0.5,
        )

    async def asyncTearDown(self):
        self.release.set()
        await self.controller.close()
        self.temp.cleanup()

    async def settle(self):
        for _ in range(10):
            await asyncio.sleep(0)

    async def test_reply_is_recorded_only_after_delivery(self):
        self.block_speech = True
        await self.controller.accept("Explain attention")
        await self.started.wait()
        self.assertFalse(any(m["role"] == "assistant"
                             for m in self.controller.history))
        self.release.set()
        await self.settle()
        self.assertEqual(self.controller.history[-1]["role"], "assistant")

    async def test_backchannel_does_not_stop_playback(self):
        self.block_speech = True
        await self.controller.accept("Explain attention")
        await self.started.wait()
        count = self.stops
        result = await self.controller.accept("uh-huh")
        self.assertEqual(result, "backchannel")
        self.assertEqual(self.stops, count)
        self.assertTrue(self.controller.busy)

    async def test_stop_does_not_cancel_job(self):
        job = self.jobs.submit("Long draft")
        await self.controller.accept("stop talking")
        self.assertEqual(self.jobs.get(job["id"])["status"], "running")

    async def test_delegate_returns_before_completion(self):
        result = await self.controller.accept("background task write a draft")
        self.assertEqual(result, "delegated")
        self.assertEqual(self.jobs.list()[0]["status"], "running")
        await self.settle()
        await self.controller.accept("Explain convolution")
        await self.settle()
        self.assertIn("A short answer.", self.spoken)

    async def test_stale_foreground_result_is_fenced(self):
        stale_release = asyncio.Event()
        old_started = asyncio.Event()

        class Stubborn:
            calls = 0

            async def run(inner, prompt, workspace, *, foreground=False):
                inner.calls += 1
                if inner.calls == 1:
                    old_started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        await stale_release.wait()
                    return "STALE"
                return "CURRENT"

        self.controller.backend = Stubborn()
        await self.controller.accept("old request")
        await old_started.wait()
        await self.controller.accept("new request")
        stale_release.set()
        await self.settle()
        self.assertNotIn("STALE", self.spoken)
        self.assertIn("CURRENT", self.spoken)

    async def test_completion_waits_for_user_and_quiet_boundary(self):
        job = self.jobs.submit("draft")
        self.jobs.items[job["id"]]["status"] = "completed"
        self.controller.user_started()
        self.assertFalse(self.controller.poll())
        self.controller.user_stopped()
        self.assertFalse(self.controller.poll())
        self.now += 1
        self.assertFalse(self.controller.poll())  # ASR is still pending.
        await self.controller.accept("stop talking")
        self.now += 1
        self.assertTrue(self.controller.poll())
        await self.settle()
        self.assertEqual(self.jobs.get(job["id"])["notified"], 1)
        self.assertIsNone(self.controller.focus)

    async def test_notice_scheduled_just_before_user_onset_is_deferred(self):
        job = self.jobs.submit("draft")
        self.jobs.items[job["id"]]["status"] = "completed"
        self.now += 1
        self.assertTrue(self.controller.poll())
        self.controller.user_started()
        self.controller.user_stopped()
        await self.settle()
        self.assertFalse(self.spoken)
        self.assertEqual(self.jobs.get(job["id"])["notified"], 0)

    async def test_old_reply_waits_for_transcript_not_vad_silence(self):
        ready = asyncio.Event()

        class Waiting:
            async def run(inner, *args, **kwargs):
                await ready.wait()
                return "OLD"

        self.controller.backend = Waiting()
        await self.controller.accept("first request")
        self.controller.user_started()
        ready.set()
        self.controller.user_stopped()
        await self.settle()
        self.assertFalse(self.spoken)
        await self.controller.accept("stop talking")

    async def test_interrupted_notice_can_be_retried(self):
        self.block_speech = True
        job = self.jobs.submit("draft")
        self.jobs.items[job["id"]]["status"] = "completed"
        self.now += 1
        self.assertTrue(self.controller.poll())
        await self.started.wait()
        await self.controller.accept("stop talking")
        await self.settle()
        self.assertEqual(self.jobs.get(job["id"])["notified"], 0)
        self.block_speech = False
        self.now += 2
        self.assertTrue(self.controller.poll())
        await self.settle()
        self.assertEqual(self.jobs.get(job["id"])["notified"], 1)

    async def test_incomplete_turn_backchannel_is_rate_limited(self):
        self.controller.user_started()
        self.controller.user_stopped()
        self.assertEqual(await self.controller.accept(
            "I would like to explain the problem because", complete=False,
        ), "hold")
        await self.settle()
        self.assertEqual(self.spoken, ["Mm-hm."])
        await self.controller.accept(
            "and there is another part", complete=False,
        )
        await self.settle()
        self.assertEqual(self.spoken, ["Mm-hm."])
        self.assertFalse(self.controller.poll())

    async def test_provider_failure_does_not_fake_success(self):
        class Failing:
            async def run(inner, *args, **kwargs):
                raise RuntimeError("provider down")

        self.controller.backend = Failing()
        await self.controller.accept("question")
        await self.settle()
        self.assertIn("unavailable", " ".join(self.spoken))
        self.assertNotIn("A short answer.", self.spoken)
        self.assertTrue(any(e[0] == "foreground_failed"
                            for e in self.jobs.events))

    async def test_reject_empty_or_oversize_input(self):
        for text in (" ", "x" * 16001):
            with self.assertRaises(ValueError):
                await self.controller.accept(text)

    async def test_unknown_background_speech_is_not_claimed_rejected(self):
        self.assertEqual(await self.controller.accept(
            "A nearby conversation", addressed=False,
        ), "ignore")
        self.assertFalse(self.spoken)
