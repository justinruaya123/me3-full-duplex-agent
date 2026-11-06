"""Real Pipecat scheduling, with fixture ASR/TTS/worker and injected VAD.

These protect voice/job lifetime boundaries, not acoustic playback, ownership,
native speech inference, or latency targets. No audio device is opened.
"""

import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; pause lifetime boundary not run",
)
class PauseLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, operation):
        from pipecat.frames.frames import (
            InputAudioRawFrame,
            StartFrame,
            TTSAudioRawFrame,
            VADUserStartedSpeakingFrame,
            VADUserStoppedSpeakingFrame,
        )
        from pipecat.processors.frame_processor import FrameProcessor

        from me3.audio_pipeline import build
        from me3.runtime import AgentRuntime

        ready = asyncio.Event()
        first_audio = asyncio.Event()
        allow_second = asyncio.Event()
        second_produced = asyncio.Event()
        asr_started = asyncio.Event()
        release_asr = asyncio.Event()
        asr_returned = asyncio.Event()
        job_started = asyncio.Event()
        release_job = asyncio.Event()
        job_cancelled = asyncio.Event()
        output = []
        first_pcm = b"\x01\x00" * 480
        retained_pcm = b"\x02\x00" * 480
        recognition_task = None

        class Source(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, StartFrame):
                    ready.set()
                await self.push_frame(frame, direction)

        class Sink(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, TTSAudioRawFrame):
                    output.append(frame.audio)
                    if frame.audio == first_pcm:
                        first_audio.set()
                await self.push_frame(frame, direction)

        class Transport:
            def __init__(self):
                self.source, self.sink = Source(), Sink()

            def input(self):
                return self.source

            def output(self):
                return self.sink

        class Speech:
            async def synthesize(self, text):
                yield first_pcm
                await allow_second.wait()
                second_produced.set()
                yield retained_pcm

            async def transcribe(self, audio):
                nonlocal recognition_task
                recognition_task = asyncio.current_task()
                asr_started.set()
                try:
                    await release_asr.wait()
                except asyncio.CancelledError:
                    # A late provider can finish after cancellation. Its empty
                    # result must still be unable to resurrect paused output.
                    await release_asr.wait()
                asr_returned.set()
                return ""

        class Turn:
            async def __call__(self, pcm):
                return False

        class Foreground:
            calls = 0

            async def run(self, prompt, workspace, *, foreground=False):
                self.calls += 1
                return "Fixture explanation."

        class Worker:
            async def run(self, prompt, workspace, *, foreground=False):
                job_started.set()
                try:
                    await release_job.wait()
                except asyncio.CancelledError:
                    job_cancelled.set()
                    raise
                return "Fixture delegated result."

        transport, foreground = Transport(), Foreground()
        config = {
            "asr_base_url": "http://localhost/v1", "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1", "tts_model": "fixture",
            "tts_voice": "fixture", "asr_key": "", "tts_key": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(Path(directory), Worker(), foreground)
            run_task = control = lifecycle = job = None
            close_invoked = False
            try:
                with patch.dict(os.environ, {"ME3_AUDIO_MODE": "headphones"}):
                    run, control = await build(
                        transport, Path(directory), runtime=runtime,
                        profile="course", speech=Speech(),
                        turn_analyzer=Turn(), config=config,
                    )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                job = control.controller.jobs.submit("Blocked fixture work")
                await asyncio.wait_for(job_started.wait(), 1)
                self.assertEqual(
                    runtime.supervisor.get(job["id"])["status"], "running",
                )
                await control.controller.accept("Explain the fixture.")
                await asyncio.wait_for(first_audio.wait(), 1)
                epoch = control.controller.epoch
                await transport.source.push_frame(
                    VADUserStartedSpeakingFrame(),
                )
                for _ in range(100):
                    if control.controller.user_speaking:
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(control.controller.user_speaking)
                allow_second.set()
                await asyncio.wait_for(second_produced.wait(), 1)
                await asyncio.sleep(0.05)
                self.assertEqual(output, [first_pcm])
                self.assertEqual(control.controller.epoch, epoch)
                await transport.source.push_frame(InputAudioRawFrame(
                    b"\0" * 640, sample_rate=16000, num_channels=1,
                ))
                await transport.source.push_frame(
                    VADUserStoppedSpeakingFrame(),
                )
                await asyncio.wait_for(asr_started.wait(), 1)
                self.assertFalse(asr_returned.is_set())
                self.assertEqual(foreground.calls, 1)
                if operation == "mute":
                    lifecycle = asyncio.create_task(control.mute())
                else:
                    close_invoked = True
                    lifecycle = asyncio.create_task(control())
                for _ in range(100):
                    if control.controller._closed:
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(control.controller._closed)
                self.assertFalse(asr_returned.is_set())
                release_asr.set()
                await asyncio.wait_for(asr_returned.wait(), 1)
                await asyncio.wait_for(lifecycle, 5)
                if recognition_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(
                            recognition_task, return_exceptions=True,
                        ), 1,
                    )
                if operation == "close":
                    await asyncio.wait_for(run_task, 5)
                else:
                    await asyncio.sleep(0.05)
                    self.assertFalse(run_task.done())
                self.assertEqual(output, [first_pcm])
                self.assertNotIn(retained_pcm, output)
                self.assertEqual(foreground.calls, 1)
                self.assertFalse(job_cancelled.is_set())
                self.assertEqual(
                    runtime.supervisor.get(job["id"])["status"], "running",
                )
                self.assertFalse(runtime.closed)
                release_job.set()
                await asyncio.wait_for(runtime.supervisor.wait(job["id"]), 1)
                self.assertEqual(
                    runtime.supervisor.get(job["id"])["status"], "completed",
                )
            finally:
                allow_second.set()
                release_asr.set()
                release_job.set()
                try:
                    if lifecycle is not None:
                        await asyncio.wait_for(
                            asyncio.gather(lifecycle, return_exceptions=True),
                            5,
                        )
                    if control is not None and not close_invoked:
                        await asyncio.wait_for(control(), 5)
                    if run_task is not None:
                        await asyncio.wait_for(
                            asyncio.gather(run_task, return_exceptions=True),
                            5,
                        )
                    if job is not None:
                        await asyncio.wait_for(
                            runtime.supervisor.wait(job["id"]), 1,
                        )
                finally:
                    await asyncio.wait_for(runtime.close(), 5)

    async def test_mute_fences_late_empty_asr_and_preserves_running_job(self):
        await self.exercise("mute")

    async def test_close_fences_late_empty_asr_and_preserves_running_job(self):
        await self.exercise("close")


if __name__ == "__main__":
    unittest.main()
