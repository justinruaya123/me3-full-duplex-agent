"""Incremental transcript and delivery invariants without audio models."""

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
    async def collect_clauses(self, parts):
        from me3.incremental import clauses

        async def stream():
            for part in parts:
                yield part

        return [chunk async for chunk in clauses(stream())]

    async def test_decimal_waits_for_following_delta(self):
        chunks = await self.collect_clauses((
            "The balance is 1,234.",
            "56 dollars. The receipt is ready.",
        ))
        self.assertEqual(chunks, [
            "The balance is 1,234.56 dollars.",
            "The receipt is ready.",
        ])

    async def test_sentence_chunks_are_independent_of_token_partitions(self):
        fixtures = (
            (
                "The balance is 1,234.56 dollars. The receipt is ready.",
                ["The balance is 1,234.56 dollars.", "The receipt is ready."],
            ),
            (
                "Use v1.2.3 on 2026.11.07. Keep the original.",
                ["Use v1.2.3 on 2026.11.07.", "Keep the original."],
            ),
            (
                "Dr. Ellis and Prof. Chen meet at 9 a.m. tomorrow. "
                "The notes include e.g. dates etc. for review. Finished!",
                [
                    "Dr. Ellis and Prof. Chen meet at 9 a.m. tomorrow.",
                    "The notes include e.g. dates etc. for review.",
                    "Finished!",
                ],
            ),
            (
                "Mr. A. Smith uses the U.S. report; Mrs. Jones agrees? Yes.",
                [
                    "Mr. A. Smith uses the U.S. report;",
                    "Mrs. Jones agrees?",
                    "Yes.",
                ],
            ),
        )
        for text, expected in fixtures:
            with self.subTest(text=text, partition="whole"):
                self.assertEqual(await self.collect_clauses((text,)), expected)
            for split in range(1, len(text)):
                with self.subTest(text=text, split=split):
                    self.assertEqual(
                        await self.collect_clauses(
                            (text[:split], text[split:])
                        ),
                        expected,
                    )
            for width in range(1, 8):
                with self.subTest(text=text, width=width):
                    self.assertEqual(
                        await self.collect_clauses(
                            text[index:index + width]
                            for index in range(0, len(text), width)
                        ),
                        expected,
                    )

    async def test_punctuation_at_delta_end_does_not_release_speech(self):
        from me3.incremental import clauses

        started, release = asyncio.Event(), asyncio.Event()

        async def source():
            started.set()
            yield "The balance is 1,234."
            await release.wait()
            yield "56 dollars. "
            await release.wait()

        source_stream = source()
        output = clauses(source_stream)
        first = asyncio.create_task(anext(output))
        try:
            await asyncio.wait_for(started.wait(), 0.5)
            self.assertFalse(first.done())
            release.set()
            self.assertEqual(
                await asyncio.wait_for(first, 0.5),
                "The balance is 1,234.56 dollars.",
            )
        finally:
            release.set()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await output.aclose()
            await source_stream.aclose()

    async def test_confirmed_clauses_yield_without_reading_more_source(self):
        from me3.incremental import clauses

        pulled = []

        async def source():
            pulled.append(1)
            yield "First clause. Second clause! "
            pulled.append(2)
            yield "Third clause?"

        source_stream = source()
        output = clauses(source_stream)
        try:
            self.assertEqual(
                await asyncio.wait_for(anext(output), 0.5), "First clause."
            )
            self.assertEqual(pulled, [1])
            self.assertEqual(
                await asyncio.wait_for(anext(output), 0.5), "Second clause!"
            )
            self.assertEqual(pulled, [1])
            self.assertEqual(
                await asyncio.wait_for(anext(output), 0.5), "Third clause?"
            )
            self.assertEqual(pulled, [1, 2])
        finally:
            await output.aclose()
            await source_stream.aclose()

    async def test_length_bound_preserves_words_numbers_and_versions(self):
        text = (
            "Careful readings remain useful " * 9
            + "1,234.56 2026.11.07 v12.34.56 extraordinary. "
            + "Additional measurements stay in source order " * 9
        )
        whole = await self.collect_clauses((text,))
        for width in (1, 2, 7, 53):
            with self.subTest(width=width):
                chunks = await self.collect_clauses(
                    text[index:index + width]
                    for index in range(0, len(text), width)
                )
                self.assertEqual(chunks, whole)
                self.assertEqual(" ".join(chunks).split(), text.split())
                self.assertTrue(all(len(chunk) <= 240 for chunk in chunks))

    async def test_emergency_split_preserves_numeric_and_word_spans(self):
        prefix = "steady " * 34
        for span in ("1,234.56", "2026.11.07", "v12.34.56", "extraordinary"):
            text = prefix + span + " remains complete. Next item."
            expected = [
                prefix.rstrip(), span + " remains complete.", "Next item."
            ]
            for width in (1, 2, 7, len(text)):
                with self.subTest(span=span, width=width):
                    self.assertEqual(
                        await self.collect_clauses(
                            text[index:index + width]
                            for index in range(0, len(text), width)
                        ),
                        expected,
                    )

    async def test_indivisible_over_limit_token_fails_without_truncation(self):
        from me3.incremental import clauses

        for token in ("x" * 241, "1" * 241, "v1." * 81):
            for parts in ((token,), tuple(token)):
                with self.subTest(token=token[:10], fragmented=len(parts) > 1):
                    async def source():
                        for part in parts:
                            yield part

                    spoken = []
                    with self.assertRaises(BufferError):
                        async for chunk in clauses(source()):
                            spoken.append(chunk)
                    self.assertEqual(spoken, [])

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
