"""Finite text hold guards with fixture ASR/readiness, not acoustic scoring."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from test_duplex_v1 import Backend, Jobs

from me3.capture import RollingCapture
from me3.duplex import DuplexController


class HesitationTests(unittest.IsolatedAsyncioTestCase):
    async def final_event(self, text, *, complete=True):
        events = []

        async def recognize(pcm):
            return text

        async def analyze(pcm):
            return complete

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture("s", recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            await capture.finish()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].text, text)
            self.assertTrue(events[0].capture_ended)
            return events[0]
        finally:
            await capture.close()

    async def test_explicit_hold_at_tail_vetoes_acoustic_completion(self):
        for text in (
            "Give me a second.",
            "Background task build a site, give me a moment please.",
            "Let me think...",
            "Let me think about it.",
            "I lost my train of thought.",
            "I've lost my train of thought.",
            "I’ve lost my train of thought.",
            "I forgot what I was going to say.",
        ):
            with self.subTest(text=text):
                self.assertFalse((await self.final_event(text)).committed)

    async def test_filled_pause_at_tail_vetoes_acoustic_completion(self):
        for text in (
            "Background task build a site, um.",
            "Send it to Alice, uh...",
            "I want to, uhh",
            "Erm.",
            "Hmm...",
        ):
            with self.subTest(text=text):
                self.assertFalse((await self.final_event(text)).committed)

    async def test_explicit_cutoff_and_narrow_unfinished_tails_hold(self):
        for text in (
            "Background task build a",
            "Make it blue and",
            "Send it to",
            "I I",
            "I want the the",
            "Build a-a",
            "Can you b-b-",
            "I want to build—",
            "I want...",
            "Build a site…",
        ):
            with self.subTest(text=text):
                self.assertFalse((await self.final_event(text)).committed)

    async def test_completed_requests_keep_disfluency_verbatim_and_commit(
        self,
    ):
        for text in (
            "Background task build a blue site.",
            "I I want to build a blue site.",
            "Can you b-b-build a blue site?",
            "Um, what is two plus two?",
            "Let me think. Build a blue site.",
            "Give me a second opinion.",
            "What does um mean?",
            "Yes, yes.",
            "No, no.",
            "Say ha-ha.",
            "Use a go-go theme.",
            "Who should I send it to?",
            "Build a site about lost trains of thought.",
        ):
            with self.subTest(text=text):
                self.assertTrue((await self.final_event(text)).committed)

    async def test_completed_text_still_requires_full_turn_readiness(self):
        event = await self.final_event(
            "Um, build a blue site.", complete=False,
        )
        self.assertFalse(event.committed)

    async def test_held_fragment_resumes_full_pcm_without_action(self):
        first = b"\x01\x00" * 320
        continuation = b"\x02\x00" * 640
        fragment = "Background task build a, um."
        finished = "Background task build a, um, blue site."
        recognized, analyzed, events, decisions, spoken, stopped = (
            [], [], [], [], [], [],
        )

        async def recognize(pcm):
            recognized.append(pcm)
            return fragment if pcm == first else finished

        async def analyze(pcm):
            analyzed.append(pcm)
            return True

        async def speak(text):
            spoken.append(text)
            return True

        async def stop():
            stopped.append(True)

        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(Path(directory))
            controller = DuplexController(jobs, Backend(), speak, stop)

            async def emit(event, pcm):
                events.append((event, pcm))
                decisions.append(await controller.transcript(event))

            capture = RollingCapture("s", recognize, analyze, emit)
            try:
                capture.begin()
                controller.user_started()
                capture.feed(first)
                controller.user_stopped()
                await capture.finish()
                turn = events[-1][0].turn_id
                self.assertEqual(decisions, ["hold"])
                self.assertFalse(capture.committed)
                self.assertFalse(jobs.list())
                self.assertFalse(controller.history)
                self.assertFalse(spoken)
                self.assertFalse(stopped)

                # Another final over the same silence cannot force a commit.
                await capture.finish()
                self.assertEqual(decisions, ["hold", "hold"])
                self.assertEqual(bytes(capture.audio), first)
                capture.begin()
                controller.user_started()
                capture.feed(continuation)
                controller.user_stopped()
                await capture.finish()
                self.assertEqual(decisions[-1], "delegated")
                self.assertEqual(recognized, [first, first + continuation])
                self.assertEqual(
                    analyzed, [first, first, first + continuation]
                )
                event, pcm = events[-1]
                self.assertEqual(event.turn_id, turn)
                self.assertEqual(event.revision, 3)
                self.assertEqual(event.text, finished)
                self.assertEqual(pcm, first + continuation)
                self.assertTrue(event.committed)
                self.assertEqual(len(jobs.list()), 1)
                self.assertEqual(
                    jobs.list()[0]["prompt"], "build a, um, blue site."
                )
            finally:
                await capture.close()
                await controller.close()

    async def test_resumed_hold_fences_stale_finish_generation(self):
        events = []
        text = "Let me think."

        async def recognize(pcm):
            return text

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append((event, pcm))

        capture = RollingCapture("s", recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            old_generation = capture.generation
            await capture.finish()
            self.assertFalse(events[-1][0].committed)
            capture.begin()
            capture.feed(b"\x02\x00" * 320)
            await capture.finish(generation=old_generation)
            self.assertTrue(capture.active)
            self.assertEqual(len(events), 1)
            text = "Let me think. Build a blue site."
            await capture.finish(generation=capture.generation)
            self.assertEqual(len(events), 2)
            self.assertTrue(events[-1][0].committed)
            self.assertEqual(len(events[-1][1]), 1280)
        finally:
            await capture.close()

    async def test_late_held_final_cannot_revise_resumed_complete_turn(self):
        started, release = asyncio.Event(), asyncio.Event()
        events, recognized = [], []
        first = b"\x01\x00" * 320
        continuation = b"\x02\x00" * 320

        async def recognize(pcm):
            recognized.append(pcm)
            if pcm == first:
                started.set()
                await release.wait()
                return "Let me think."
            return "Let me think. Build a blue site."

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append((event, pcm))

        capture = RollingCapture("s", recognize, analyze, emit)
        finals = []
        try:
            capture.begin()
            capture.feed(first)
            finals.append(asyncio.create_task(capture.finish()))
            await asyncio.wait_for(started.wait(), 1)
            capture.begin()
            capture.feed(continuation)
            finals.append(asyncio.create_task(capture.finish()))
            release.set()
            await asyncio.wait_for(asyncio.gather(*finals), 1)
            self.assertEqual(recognized, [first, first + continuation])
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0][0].committed)
            self.assertEqual(events[0][0].revision, 1)
            self.assertEqual(events[0][1], first + continuation)
        finally:
            release.set()
            await asyncio.gather(*finals, return_exceptions=True)
            await capture.close()
