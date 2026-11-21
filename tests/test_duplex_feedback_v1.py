import asyncio
import os
import time
import unittest
from unittest.mock import patch

from integrations.fdbench_pi import DigitalDevice
from me3.parakeet_voice import Playback


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cue = b"\x01\x03" * 2400
        self.word = b"\x32\x05" * 480
        self.device = DigitalDevice()
        with patch.dict(os.environ, ME3_VOICE_TTS="bmo", ME3_WAIT_CUE_MS="1000"), \
                patch("me3.bmo.read_clip", return_value=self.cue):
            self.playback = Playback(self.device)

    async def test_delayed_first_word_preempts_cached_wait_in_the_same_callback(self):
        ready = asyncio.Event()

        async def synthesize(_):
            await ready.wait()
            yield self.word

        self.playback.engine.synthesize = synthesize
        with patch("me3.parakeet_voice.emit") as events:
            self.playback.arm_feedback("r", time.monotonic() - 1.1)
            reply = asyncio.create_task(self.playback.speak("real reply", receipt="r"))
            await asyncio.sleep(0)
            self.assertEqual(self.device.render(480), self.cue[:960])
            self.assertIsNone(self.device.first_reply_signal)
            ready.set()
            await asyncio.sleep(0)
            self.assertEqual(self.device.render(480), self.word)
            await reply
            self.assertEqual(self.device.render(480), b"")
        kinds = [c.args[0] for c in events.call_args_list]
        self.assertEqual(kinds.count("wait_cue_output"), 1)
        self.assertEqual(kinds.count("playing"), 1)
        self.assertEqual(events.call_args.kwargs["signal_frames"], 480)

    async def test_fast_pcm_tool_audio_and_user_resumption_retire_wait(self):
        for source in ("answer", "tool", "user"):
            self.playback.arm_feedback(source, time.monotonic() - 5)
            if source == "user":
                self.playback.hold(True)
                self.playback.hold(False)
            else:
                await self.device.enqueue(self.word)
                self.assertEqual(self.device.render(480), self.word)
            self.assertEqual(self.device.render(480), b"")
            await self.playback.cut()

    def test_sustained_speech_opportunity_requires_duration_recent_words_and_a_dip(self):
        from me3.parakeet_voice import SpeechDip
        detector = SpeechDip()
        for frame in range(1, 315):
            self.assertFalse(detector.observe(frame, 2000, frame // 10))
        for frame in (315, 316):
            self.assertFalse(detector.observe(frame, 500, 31))
        self.assertTrue(detector.observe(317, 500, 31))
        self.assertFalse(detector.observe(318, 500, 31))
        for frame in range(319, 400):
            self.assertFalse(detector.observe(frame, 2000, 31))
        for frame in range(400, 405):
            self.assertFalse(detector.observe(frame, 500, 31))
