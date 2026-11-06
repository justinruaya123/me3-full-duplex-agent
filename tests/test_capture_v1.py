"""Rolling ASR races: final readiness never follows silence alone."""

import asyncio
import unittest


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_final_replaces_waiting_partial_after_speech_resumes(
        self,
    ):
        from me3.capture import RollingCapture

        started, release, events = asyncio.Event(), asyncio.Event(), []
        calls, cancelled = [], []

        async def recognize(pcm):
            calls.append(pcm)
            if len(calls) == 2:
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.append(pcm)
                    raise
            return "use the complete corrected request"

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append((event, pcm))

        capture = RollingCapture("s", recognize, analyze, emit)
        finals = []
        first = b"\x01\x00" * 16000
        correction = b"\x02\x00" * 16000
        try:
            capture.begin()
            capture.feed(first)
            await capture._partial
            finals.append(asyncio.create_task(capture.finish()))
            await started.wait()  # Final ASR now owns the native slot.
            capture.begin()
            capture.feed(correction)
            await asyncio.sleep(0)  # A new partial queues behind that final.
            finals.append(asyncio.create_task(capture.finish()))
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.wait_for(
                asyncio.gather(*finals, return_exceptions=True), 1
            )
            self.assertIsNone(results[-1])
            self.assertFalse(cancelled)
            self.assertEqual(calls, [first, first, first + correction])
            committed = [(e, pcm) for e, pcm in events if e.committed]
            self.assertEqual(len(committed), 1)
            self.assertEqual(committed[0][1], first + correction)
        finally:
            release.set()
            await asyncio.gather(*finals, return_exceptions=True)
            await capture.close()

    async def test_resumed_turn_replaces_stale_queued_final_with_fresh_audio(
        self,
    ):
        from me3.capture import RollingCapture

        started, release, events = asyncio.Event(), asyncio.Event(), []
        calls, cancelled = [], []

        async def recognize(pcm):
            calls.append(pcm)
            if len(calls) == 1:
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.append(pcm)
                    raise
            return "use the complete corrected request"

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append((event, pcm))

        capture = RollingCapture("s", recognize, analyze, emit)
        finals = []
        first = b"\x01\x00" * 16000
        correction = b"\x02\x00" * 3200
        try:
            capture.begin()
            capture.feed(first)
            await started.wait()  # Native partial inference is still running.
            finals.append(asyncio.create_task(capture.finish()))
            # The first final waits behind that partial.
            await asyncio.sleep(0)
            capture.begin()
            capture.feed(correction)
            finals.append(asyncio.create_task(capture.finish()))
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.wait_for(
                asyncio.gather(*finals, return_exceptions=True), 1
            )
            self.assertIsNone(results[-1])
            self.assertFalse(cancelled, "Running ASR must retain its capacity")
            self.assertEqual(calls, [first, first + correction])
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0][0].committed)
            self.assertEqual(events[0][1], first + correction)
        finally:
            release.set()
            await asyncio.gather(*finals, return_exceptions=True)
            await capture.close()

    async def test_incomplete_acoustic_turn_only_emits_provisional_text(self):
        from me3.capture import RollingCapture

        events = []

        async def recognize(pcm):
            return "background task build"

        async def analyze(pcm):
            return False

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture("s", recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 16000)
            await capture.finish()
            self.assertTrue(events)
            self.assertFalse(any(e.committed for e in events))
        finally:
            await capture.close()

    async def test_resumed_audio_fences_late_final_hypothesis(self):
        from me3.capture import RollingCapture

        release, started, events = asyncio.Event(), asyncio.Event(), []

        async def recognize(pcm):
            started.set()
            await release.wait()
            return "background task obsolete"

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture("s", recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 16000)
            final = asyncio.create_task(capture.finish())
            await started.wait()
            capture.begin()
            capture.feed(b"\x02\x00" * 320)
            release.set()
            await final
            self.assertFalse(any(e.committed for e in events))
        finally:
            release.set()
            await capture.close()

    async def test_overflow_and_transcript_gap_cannot_commit_fragment(self):
        from me3.capture import RollingCapture

        events = []

        async def recognize(pcm):
            return "send [inaudible] to Alice"

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture("s", recognize, analyze, emit, max_seconds=1)
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 16000)
            await capture.finish()
            self.assertFalse(any(e.committed for e in events))
            capture.begin()  # Resume the unfinished turn before adding audio.
            with self.assertRaises(BufferError):
                capture.feed(b"\x01\x00" * 320)
        finally:
            await capture.close()

    async def test_pending_snapshot_overflow_invalidates_authorization(
        self,
    ):
        from me3.capture import RollingCapture

        started, release, events = asyncio.Event(), asyncio.Event(), []

        async def recognize(pcm):
            started.set()
            await release.wait()
            return "background task obsolete"

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture("s", recognize, analyze, emit)
        final = None
        try:
            capture.begin()
            capture.feed(bytes(32000))  # Starts one partial snapshot.
            await started.wait()
            final = asyncio.create_task(capture.finish())
            await asyncio.sleep(0)
            with self.assertRaises(BufferError):
                await asyncio.wait_for(capture.finish(), 0.2)
            release.set()
            await final
            self.assertFalse(any(event.committed for event in events))
        finally:
            release.set()
            if final:
                await asyncio.gather(final, return_exceptions=True)
            await capture.close()
