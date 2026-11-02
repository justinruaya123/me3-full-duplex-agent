"""Configuration checks plus an optional real-Pipecat API smoke test."""

import importlib.util
import unittest

from me3.duplex_voice import settings


class SettingsTests(unittest.TestCase):
    def test_missing_endpoints_fail_before_loading_audio(self):
        with self.assertRaises(ValueError):
            settings({})

    def test_explicit_local_providers(self):
        env = {
            "ME3_ASR_BASE_URL": "http://localhost:8000/v1",
            "ME3_ASR_MODEL": "whisper-local",
            "ME3_TTS_BASE_URL": "http://localhost:8880/v1",
            "ME3_TTS_MODEL": "kokoro",
            "ME3_TTS_VOICE": "af_heart",
        }
        self.assertEqual(settings(env)["asr_model"], "whisper-local")
        env["ME3_ASR_BASE_URL"] = "file:///tmp/private"
        with self.assertRaises(ValueError):
            settings(env)

    @unittest.skipUnless(importlib.util.find_spec("pipecat"),
                         "Pipecat is not installed; API smoke not run")
    def test_installed_pipecat_api(self):
        from pipecat.frames.frames import (
            BotStartedSpeakingFrame, BotStoppedSpeakingFrame, TTSSpeakFrame,
        )
        from pipecat.pipeline.runner import WorkerRunner
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker
        from pipecat.processors.audio.vad_processor import VADProcessor
        from pipecat.processors.frame_processor import FrameProcessor

        self.assertTrue(hasattr(FrameProcessor, "broadcast_interruption"))
        self.assertEqual(TTSSpeakFrame("hello").text, "hello")
        self.assertTrue(all((WorkerRunner, PipelineParams, PipelineWorker,
                             VADProcessor, BotStartedSpeakingFrame,
                             BotStoppedSpeakingFrame)))
