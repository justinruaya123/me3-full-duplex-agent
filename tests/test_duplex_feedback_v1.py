import asyncio
import os
import time
import unittest
from unittest.mock import patch

from integrations.fdbench_pi import DigitalDevice
from me3.parakeet_voice import Playback


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def test_committed_turn_has_a_short_nonverbal_receipt(self):
        self.assertLessEqual(len(self.playback.wait_pcm), 24000 * 2 * .15)
        self.assertNotEqual(bytes(self.playback.wait_pcm), self.cue)

    def test_unfinished_turn_is_quiet_in_normal_duplex(self):
        from types import SimpleNamespace
        self.playback.held = self.playback.allow_cue = True
        self.playback.acknowledge(SimpleNamespace(id="a", text="I was going to tell you about the", frames=150))
        self.assertFalse(self.device.listening_cue)

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
            self.assertEqual(self.device.render(480), bytes(self.playback.wait_pcm[:960]))
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

    async def test_search_cue_after_commit_tone_is_still_scheduled(self):
        from me3.parakeet_voice import commands
        from types import SimpleNamespace

        self.playback.arm_feedback("r", time.monotonic() - 2)
        self.device.render(480)
        self.assertIsNotNone(self.playback.wait_feedback.first_output)
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb") as stream, os.fdopen(write_fd, "wb") as sender:
            sender.write(b'{"op":"say","text":"Searching.","epoch":0,"idle_only":true,'
                         b'"search_cue":true,"cached":true}\n{"op":"close"}\n')
            sender.flush()
            with patch("me3.parakeet_voice.sys.stdin", SimpleNamespace(buffer=stream)):
                await asyncio.wait_for(commands(self.playback), 2)
        self.assertIsNotNone(self.playback.task)
        await asyncio.sleep(0)  # Let the scheduled speaker enqueue its cached PCM.
        self.assertEqual(self.device.render(480), self.cue[:960])
        await self.playback.cut()

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
