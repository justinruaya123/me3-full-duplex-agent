"""Incremental transcript and delivery invariants, independent of audio models."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from test_duplex_v1 import Backend, Jobs

from me3.duplex import DuplexController


class TranscriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_provisional_delegate_and_stop_never_authorize(self):
        from me3.incremental import TranscriptRevision

        with tempfile.TemporaryDirectory() as directory:
            jobs, spoken, stopped = Jobs(Path(directory)), [], []

            async def speak(text):
                spoken.append(text)
                return True

            async def stop():
                stopped.append(True)

            controller = DuplexController(jobs, Backend(), speak, stop)
            try:
                for revision, text in enumerate(
                    ["background task delete data", "stop talking"], 1
                ):
                    event = TranscriptRevision(
                        "s", "t", revision, text, 0, 1, committed=False
                    )
                    self.assertEqual(
                        await controller.transcript(event), "hold"
                    )
                self.assertFalse(jobs.list())
                self.assertFalse(controller.history)
                self.assertFalse(stopped)
                self.assertFalse(spoken)
            finally:
                await controller.close()

    async def test_commit_is_once_and_older_revisions_are_ignored(self):
        from me3.incremental import TranscriptRevision

        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(Path(directory))

            async def speak(text):
                return True

            async def stop():
                pass

            controller = DuplexController(jobs, Backend(), speak, stop)
            try:
                event = TranscriptRevision(
                    "s", "t", 2, "background task draft", 0, 1, committed=True
                )
                self.assertEqual(
                    await controller.transcript(event), "delegated"
                )
                self.assertEqual(await controller.transcript(event), "stale")
                stale = TranscriptRevision(
                    "s", "t", 1, "background task wrong", 0, 1, committed=True
                )
                self.assertEqual(await controller.transcript(stale), "stale")
                self.assertEqual(len(jobs.list()), 1)
            finally:
                await controller.close()

    def test_rolling_revisions_keep_stability_separate_from_commit(self):
        from me3.incremental import RollingTranscript

        rolling = RollingTranscript("s", "t")
        a = rolling.update("build a red site", 0, 1)
        b = rolling.update("build a blue site", 0, 2)
        self.assertFalse(a.committed)
        self.assertEqual(b.stable_prefix, "build a")
        final = rolling.update("build a blue site", 0, 3, committed=True)
        self.assertTrue(final.committed)
        self.assertGreater(final.revision, b.revision)


class PlaybackTests(unittest.TestCase):
    def test_late_receipt_cannot_confirm_new_audio(self):
        from me3.incremental import PlaybackLedger

        ledger = PlaybackLedger()
        old = ledger.begin("old")
        ledger.invalidate()
        new = ledger.begin("new")
        self.assertFalse(ledger.started(old))
        self.assertFalse(ledger.completed(old))
        self.assertFalse(ledger.delivered(new))
        self.assertTrue(ledger.started(new))
        self.assertTrue(ledger.completed(new))
        self.assertTrue(ledger.delivered(new))

    def test_provisional_pause_preserves_unplayed_pcm(self):
        from me3.incremental import PCMBuffer

        output = PCMBuffer(max_bytes=16)
        output.append(b"\x01\x00\x02\x00\x03\x00")
        self.assertEqual(output.read(2), b"\x01\x00")
        output.pause()
        self.assertEqual(output.read(4), b"\x00" * 4)
        output.resume()
        self.assertEqual(output.read(4), b"\x02\x00\x03\x00")
        output.append(b"\x04\x00")
        output.flush()
        self.assertEqual(output.read(2), b"\x00\x00")

    def test_buffer_overflow_fails_instead_of_dropping_audio_silently(self):
        from me3.incremental import PCMBuffer

        output = PCMBuffer(max_bytes=4)
        with self.assertRaises(BufferError):
            output.append(b"123456")


class ClauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_clause_plays_before_generation_finishes(self):
        release, first = asyncio.Event(), asyncio.Event()

        class Streaming:
            async def stream(self, prompt):
                yield "First clause. "
                await release.wait()
                yield "Second clause."

        with tempfile.TemporaryDirectory() as directory:
            spoken = []

            async def speak(text):
                spoken.append(text)
                first.set()
                return True

            async def stop():
                pass

            controller = DuplexController(
                Jobs(Path(directory)), Streaming(), speak, stop
            )
            try:
                await controller.accept("explain")
                await asyncio.wait_for(first.wait(), 0.5)
                self.assertEqual(spoken, ["First clause."])
                release.set()
                for _ in range(20):
                    await asyncio.sleep(0)
                self.assertEqual(spoken, ["First clause.", "Second clause."])
            finally:
                release.set()
                await controller.close()
