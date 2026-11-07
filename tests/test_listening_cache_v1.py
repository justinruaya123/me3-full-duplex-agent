"""Only the neutral cue is memoized in its configured voice instance."""

import unittest

from me3.audio_pipeline import ConfiguredSpeech


class ListeningCacheTests(unittest.IsolatedAsyncioTestCase):
    def speech(self, chunks):
        class TTS:
            calls = 0

            async def synthesize(inner, text):
                inner.calls += 1
                for chunk in chunks:
                    yield chunk

        speech = object.__new__(ConfiguredSpeech)
        speech.tts = TTS()
        speech._listening_clip = None
        return speech

    async def audio(self, speech, text="Mm-hm."):
        return b"".join([p async for p in speech.synthesize(text)])

    async def test_same_cue_reuses_exact_pcm_only_in_same_voice_instance(self):
        first = self.speech([b"\x01\x00" * 100])
        second = self.speech([b"\x02\x00" * 100])
        self.assertEqual(await self.audio(first), await self.audio(first))
        self.assertEqual(first.tts.calls, 1)
        self.assertNotEqual(await self.audio(first), await self.audio(second))

    async def test_ordinary_replies_are_never_cached(self):
        speech = self.speech([bytes(20)])
        await self.audio(speech, "A normal answer.")
        await self.audio(speech, "A normal answer.")
        self.assertEqual(speech.tts.calls, 2)

    async def test_cancelled_synthesis_cannot_publish_partial_clip(self):
        speech = self.speech([b"\x01\x00" * 100, b"\x02\x00" * 100])
        stream = speech.synthesize("Mm-hm.")
        await anext(stream)
        await stream.aclose()
        self.assertEqual(await self.audio(speech),
                         b"\x01\x00" * 100 + b"\x02\x00" * 100)
        self.assertEqual(speech.tts.calls, 2)

    async def test_oversize_clip_is_streamed_without_unbounded_cache(self):
        speech = self.speech([bytes(96002)])
        self.assertEqual(len(await self.audio(speech)), 96002)
        await self.audio(speech)
        self.assertEqual(speech.tts.calls, 2)
