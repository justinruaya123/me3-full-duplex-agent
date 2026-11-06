"""Proposed project boundary tests; real Pipecat, all inference is fixture-only.

These deliberately inject VAD events: they measure pause/authorization behavior,
not Silero detection, speaker identity, physical playback or acoustic latency.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

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


class ProvisionalPauseTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, transcript, *, complete):
        ready = asyncio.Event()
        first_audio = asyncio.Event()
        allow_second = asyncio.Event()
        recognized = asyncio.Event()
        second_audio = asyncio.Event()
        output = []
        first_pcm = b"\x01\x00" * 480
        second_pcm = b"\x02\x00" * 480

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
                    elif frame.audio == second_pcm:
                        second_audio.set()
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
                yield second_pcm

            async def transcribe(self, audio):
                recognized.set()
                return transcript

        class Turn:
            async def __call__(self, pcm):
                return complete

        class Backend:
            calls = 0

            async def run(self, prompt, workspace, *, foreground=False):
                self.calls += 1
                return "Fixture explanation."

        transport, backend = Transport(), Backend()
        config = {
            "asr_base_url": "http://localhost/v1", "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1", "tts_model": "fixture",
            "tts_voice": "fixture", "asr_key": "", "tts_key": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(Path(directory), backend, backend)
            run_task = control = None
            try:
                run, control = await build(
                    transport, Path(directory), runtime=runtime,
                    profile="course", speech=Speech(), turn_analyzer=Turn(),
                    config=config,
                )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                await control.controller.accept("Explain the fixture.")
                await asyncio.wait_for(first_audio.wait(), 1)
                epoch = control.controller.epoch
                await transport.source.push_frame(VADUserStartedSpeakingFrame())
                for _ in range(100):
                    if control.controller.user_speaking:
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(control.controller.user_speaking)
                allow_second.set()
                await asyncio.sleep(0.05)
                self.assertFalse(second_audio.is_set(), "Onset must pause PCM")
                self.assertEqual(control.controller.epoch, epoch)
                self.assertEqual(backend.calls, 1)
                self.assertFalse(runtime.supervisor.list())
                await transport.source.push_frame(InputAudioRawFrame(
                    b"\0" * 640, sample_rate=16000, num_channels=1,
                ))
                await transport.source.push_frame(VADUserStoppedSpeakingFrame())
                await asyncio.wait_for(recognized.wait(), 1)
                if transcript and not complete:
                    await asyncio.sleep(0.1)
                    self.assertFalse(second_audio.is_set())
                    self.assertEqual(control.controller.epoch, epoch)
                    self.assertEqual(backend.calls, 1)
                    self.assertFalse(runtime.supervisor.list())
                    return
                for _ in range(100):
                    if second_audio.is_set() or run_task.done():
                        break
                    await asyncio.sleep(0.005)
                if transcript:
                    self.assertTrue(second_audio.is_set(),
                                    "Backchannel must resume retained PCM")
                    self.assertEqual(output, [first_pcm, second_pcm])
                    self.assertEqual(control.controller.epoch, epoch)
                else:
                    explicit_failure = (
                        run_task.done() and not run_task.cancelled()
                        and run_task.exception() is not None
                    )
                    self.assertTrue(
                        second_audio.is_set() or explicit_failure,
                        "Empty recognition must resolve the pause or report "
                        "an explicit failure after recognition completes",
                    )
                self.assertEqual(backend.calls, 1)
                self.assertFalse(runtime.supervisor.list())
            finally:
                allow_second.set()
                if control is not None:
                    await control()
                if run_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(run_task, return_exceptions=True), 5
                    )
                await runtime.close()

    async def test_backchannel_resumes_retained_pcm_without_cancellation(self):
        await self.exercise("Mm-hmm.", complete=True)

    async def test_uncommitted_stop_does_not_cancel_or_execute(self):
        await self.exercise("stop talking", complete=False)

    async def test_empty_recognition_does_not_leave_unresolved_pause(self):
        await self.exercise("", complete=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
