"""Project pause boundary tests; real Pipecat, all inference is fixture-only.

These inject VAD events to measure pause and authorization behavior, not
Silero detection, speaker identity, physical playback or acoustic latency.
"""

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path

from me3.capture import RollingCapture


class EmptyCaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events, self.resolved = [], []

    def capture(self, recognize):
        async def analyze(pcm):
            return False

        async def emit(event, pcm):
            self.events.append(event)

        return RollingCapture(
            "session", recognize, analyze, emit,
            on_empty=self.resolved.append,
        )

    async def test_empty_final_resolves_once_without_committed_transcript(
        self,
    ):
        async def recognize(pcm):
            return "   "

        capture = self.capture(recognize)
        try:
            capture.begin()
            capture.feed(bytes(640))
            await capture.finish()
            await capture.finish()
            self.assertEqual(self.resolved, [capture.generation])
            self.assertFalse(self.events)
        finally:
            await capture.close()

    async def test_empty_audio_final_resolves_without_requesting_inference(
        self,
    ):
        async def recognize(pcm):
            self.fail("No PCM must not request recognition")

        capture = self.capture(recognize)
        try:
            capture.begin()
            await capture.finish()
            self.assertEqual(self.resolved, [capture.generation])
            self.assertFalse(self.events)
        finally:
            await capture.close()

    async def test_late_empty_result_cannot_resolve_new_speech(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def recognize(pcm):
            started.set()
            await release.wait()
            return ""

        capture = self.capture(recognize)
        final = None
        try:
            capture.begin()
            capture.feed(bytes(640))
            final = asyncio.create_task(capture.finish())
            await asyncio.wait_for(started.wait(), 1)
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            release.set()
            await asyncio.wait_for(final, 1)
            self.assertFalse(self.resolved)
            self.assertFalse(self.events)
            self.assertTrue(capture.active)
        finally:
            release.set()
            if final:
                await asyncio.gather(final, return_exceptions=True)
            await capture.close()

    async def test_late_empty_result_after_close_cannot_resolve(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def recognize(pcm):
            started.set()
            await release.wait()
            return ""

        capture = self.capture(recognize)
        final = None
        try:
            capture.begin()
            capture.feed(bytes(640))
            final = asyncio.create_task(capture.finish())
            await asyncio.wait_for(started.wait(), 1)
            await capture.close()
            release.set()
            await asyncio.wait_for(final, 1)
            self.assertFalse(self.resolved)
            self.assertFalse(self.events)
        finally:
            release.set()
            if final:
                await asyncio.gather(final, return_exceptions=True)
            await capture.close()

    async def test_queued_old_finish_cannot_mark_new_speech_inactive(self):
        calls = []

        async def recognize(pcm):
            calls.append(pcm)
            return ""

        capture = self.capture(recognize)
        try:
            capture.begin()
            capture.feed(bytes(640))
            stopped_generation = capture.generation
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            await capture.finish(generation=stopped_generation)
            self.assertTrue(capture.active)
            self.assertFalse(calls)
            self.assertFalse(self.resolved)
        finally:
            await capture.close()

    async def test_prior_incomplete_text_prevents_empty_resolution(self):
        calls = []

        async def recognize(pcm):
            calls.append(pcm)
            return "please wait" if len(calls) == 1 else ""

        capture = self.capture(recognize)
        try:
            capture.begin()
            capture.feed(bytes(32000))
            await capture._partial
            capture.feed(b"\x01\x00" * 320)
            await capture.finish()
            self.assertEqual(len(self.events), 1)
            self.assertFalse(self.events[0].committed)
            self.assertFalse(self.resolved)
        finally:
            await capture.close()

    async def test_recognition_failure_propagates_without_empty_resolution(
        self,
    ):
        async def recognize(pcm):
            raise RuntimeError("fixture provider failed")

        capture = self.capture(recognize)
        try:
            capture.begin()
            capture.feed(bytes(640))
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                await capture.finish()
            self.assertFalse(self.resolved)
            self.assertFalse(self.events)
        finally:
            await capture.close()

    async def test_malformed_recognition_is_not_an_empty_resolution(self):
        async def recognize(pcm):
            return None

        capture = self.capture(recognize)
        try:
            capture.begin()
            capture.feed(bytes(640))
            with self.assertRaisesRegex(TypeError, "ASR must return text"):
                await capture.finish()
            self.assertFalse(self.resolved)
            self.assertFalse(self.events)
        finally:
            await capture.close()


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; provisional pause boundary not run",
)
class ProvisionalPauseTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, transcript, *, complete):
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
                await transport.source.push_frame(
                    VADUserStartedSpeakingFrame()
                )
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
                await transport.source.push_frame(
                    VADUserStoppedSpeakingFrame()
                )
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
                self.assertTrue(
                    second_audio.is_set(),
                    "Backchannel/empty final must resume retained PCM",
                )
                self.assertEqual(output, [first_pcm, second_pcm])
                self.assertEqual(control.controller.epoch, epoch)
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
