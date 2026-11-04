"""Rolling ASR races: final readiness never follows silence alone."""
import asyncio
import unittest


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_acoustic_turn_only_emits_provisional_text(self):
        from me3.capture import RollingCapture
        events = []

        async def recognize(pcm):
            return 'background task build'

        async def analyze(pcm):
            return False

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture('s', recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b'\x01\x00' * 16000)
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
            return 'background task obsolete'

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture('s', recognize, analyze, emit)
        try:
            capture.begin()
            capture.feed(b'\x01\x00' * 16000)
            final = asyncio.create_task(capture.finish())
            await started.wait()
            capture.begin()
            capture.feed(b'\x02\x00' * 320)
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
            return 'send [inaudible] to Alice'

        async def analyze(pcm):
            return True

        async def emit(event, pcm):
            events.append(event)

        capture = RollingCapture('s', recognize, analyze, emit, max_seconds=1)
        try:
            capture.begin()
            capture.feed(b'\x01\x00' * 16000)
            await capture.finish()
            self.assertFalse(any(e.committed for e in events))
            capture.begin()  # Resume the unfinished turn before adding audio.
            with self.assertRaises(BufferError):
                capture.feed(b'\x01\x00' * 320)
        finally:
            await capture.close()
