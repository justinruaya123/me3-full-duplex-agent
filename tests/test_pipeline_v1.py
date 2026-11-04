"""Real Pipecat scheduling with an in-process transport and fixture inference."""

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; pipeline smoke not run",
)
class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_gap_and_bot_stopped_event_do_not_confirm_entire_utterance(
        self,
    ):
        from pipecat.frames.frames import BotStoppedSpeakingFrame, StartFrame
        from pipecat.processors.frame_processor import FrameProcessor
        from test_duplex_v1 import Backend

        from me3.duplex_voice import build
        from me3.runtime import AgentRuntime

        ready, chunk_sent, release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        class Source(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, StartFrame):
                    ready.set()
                await self.push_frame(frame, direction)

        class Sink(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                await self.push_frame(frame, direction)

        class Transport:
            source = Source()
            sink = Sink()

            def input(self):
                return self.source

            def output(self):
                return self.sink

        class Speech:
            async def synthesize(self, text):
                yield b"\x01\x00" * 480
                chunk_sent.set()
                await release.wait()
                yield b"\x01\x00" * 480

            async def transcribe(self, audio):
                return "fixture"

        class Turn:
            async def __call__(self, pcm):
                return True

        config = {
            "asr_base_url": "http://localhost/v1",
            "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1",
            "tts_model": "fixture",
            "tts_voice": "fixture",
            "asr_key": "",
            "tts_key": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(Path(directory), Backend(), Backend())
            run_task = None
            try:
                run, control = await build(
                    Transport(),
                    Path(directory),
                    runtime=runtime,
                    profile="course",
                    speech=Speech(),
                    turn_analyzer=Turn(),
                    config=config,
                )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                await control.controller.accept("question")
                await asyncio.wait_for(chunk_sent.wait(), 5)
                await Transport.source.push_frame(BotStoppedSpeakingFrame())
                await asyncio.sleep(0.05)
                self.assertFalse(
                    any(
                        m["role"] == "assistant"
                        for m in control.controller.history
                    )
                )
                release.set()
                for _ in range(100):
                    if any(
                        m["role"] == "assistant"
                        for m in control.controller.history
                    ):
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(
                    control.controller.history[-1]["role"], "assistant"
                )
                await control()
                await asyncio.wait_for(run_task, 5)
                self.assertFalse(runtime.closed)
            finally:
                release.set()
                if run_task and not run_task.done():
                    run_task.cancel()
                    await asyncio.gather(run_task, return_exceptions=True)
                await runtime.close()
