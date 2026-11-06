"""Actual CPU VAD through the project pipeline; no acoustic/provider claim."""

import asyncio
import importlib.util
import tempfile
import unittest
import wave
from dataclasses import dataclass, field
from pathlib import Path

DEVELOPMENT_WAV = (
    Path(__file__).resolve().parents[1]
    / "docs/evidence/2026-11-07/d2/voice-sample.wav"
)


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; actual CPU onset regression not run",
)
class VADOnsetTests(unittest.IsolatedAsyncioTestCase):
    async def onsets(self, pcm):
        from pipecat.frames.frames import (
            DataFrame,
            InputAudioRawFrame,
            StartFrame,
        )
        from pipecat.processors.frame_processor import FrameProcessor

        from me3.audio_pipeline import build
        from me3.runtime import AgentRuntime

        ready = asyncio.Event()

        @dataclass
        class SampleBoundaryFrame(DataFrame):
            reached: asyncio.Event = field(default_factory=asyncio.Event)

        class Source(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, StartFrame):
                    ready.set()
                await self.push_frame(frame, direction)

        class Sink(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, SampleBoundaryFrame):
                    frame.reached.set()
                await self.push_frame(frame, direction)

        class Transport:
            def __init__(self):
                self.source, self.sink = Source(), Sink()

            def input(self):
                return self.source

            def output(self):
                return self.sink

        class UnusedInference:
            async def run(self, *args, **kwargs):
                raise AssertionError("Onset cannot request foreground/jobs")

            async def transcribe(self, audio):
                raise AssertionError("This short onset probe cannot call ASR")

            async def synthesize(self, text):
                raise AssertionError("Onset cannot call TTS")
                yield b""  # Keep the fixture's async-iterator contract.

            async def __call__(self, pcm):
                raise AssertionError("This onset probe cannot call SmartTurn")

        config = {
            "asr_base_url": "http://localhost/v1", "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1", "tts_model": "fixture",
            "tts_voice": "fixture", "asr_key": "", "tts_key": "",
        }
        transport, inference = Transport(), UnusedInference()
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(Path(directory), inference, inference)
            run_task = control = None
            try:
                run, control = await build(
                    transport, Path(directory), runtime=runtime,
                    profile="course", speech=inference,
                    turn_analyzer=inference, config=config,
                )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                speaking = False
                for offset in range(0, len(pcm), 640):
                    chunk = pcm[offset:offset + 640]
                    await transport.source.push_frame(InputAudioRawFrame(
                        chunk, sample_rate=16000, num_channels=1,
                    ))
                    boundary = SampleBoundaryFrame()
                    await transport.source.push_frame(boundary)
                    await asyncio.wait_for(boundary.reached.wait(), 1)
                    if run_task.done():
                        run_task.result()
                    current = control.controller.user_speaking
                    if current and not speaking:
                        observed.append((offset + len(chunk)) / 32000)
                    speaking = current
                self.assertFalse(runtime.supervisor.list())
                self.assertFalse(control.controller.history)
            finally:
                if control is not None:
                    await control()
                if run_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(run_task, return_exceptions=True), 5
                    )
                await runtime.close()
        return observed

    async def test_quiet_development_speech_pauses_within_450ms(self):
        import numpy as np
        import soxr

        with wave.open(str(DEVELOPMENT_WAV), "rb") as stream:
            self.assertEqual(stream.getnchannels(), 1)
            self.assertEqual(stream.getsampwidth(), 2)
            source_rate = stream.getframerate()
            samples = np.frombuffer(
                stream.readframes(stream.getnframes()), "<i2"
            ).astype(np.float64) / 32768
        speech = soxr.resample(samples, source_rate, 16000, quality="HQ")
        # Independent digital reference, frozen before gain/noise changes.
        onset_bin = next(
            start for start in range(0, len(speech), 160)
            if np.sqrt(np.mean(speech[start:start + 160] ** 2))
            >= 10 ** (-50 / 20)
        )
        prefix_samples = 12000  # 750 ms warm silence.
        onset_s = (prefix_samples + onset_bin) / 16000
        signal = np.concatenate((
            np.zeros(prefix_samples), speech * 10 ** (-24 / 20),
        ))
        # Stop at the project budget, before rolling ASR is eligible.
        signal = signal[:int((onset_s + 0.45) * 16000)]
        pcm = np.round(signal * 32768).astype("<i2").tobytes()
        starts = await self.onsets(pcm)
        self.assertTrue(starts, "No provisional onset within 450 ms")
        self.assertGreaterEqual(starts[0], onset_s)
        self.assertLessEqual(starts[0] - onset_s, 0.45)

    async def test_noise_and_clicks_do_not_create_provisional_turns(self):
        import numpy as np

        samples = np.random.default_rng(231).normal(
            scale=10 ** (-30 / 20), size=16000 * 6,
        )
        for at in range(8000, len(samples), 8000):
            samples[at] += 0.8
        self.assertLess(float(np.max(np.abs(samples))), 1)
        pcm = np.round(samples * 32768).astype("<i2").tobytes()
        self.assertEqual(await self.onsets(pcm), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
