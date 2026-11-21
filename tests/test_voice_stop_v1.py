import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from integrations.fdbench_pi import DigitalDevice
from me3.deepgram import DeepgramStream
from me3.parakeet import FRAME, Stream
from me3.parakeet_voice import Playback, commands, local_turns


class VoiceStopTests(unittest.IsolatedAsyncioTestCase):
    async def play_turn(self, partial, final, *, near=True, complete=True,
                        provider=DeepgramStream, endpoint=100):
        from pipecat.audio.vad.vad_analyzer import VADState

        wire = Mock(spec=provider, current=None)
        item = SimpleNamespace(id="item", text=partial, settled_text=partial,
                               frames=0, finalized_frames=100, endpoint_frames=endpoint)

        async def begin():
            wire.current = item
            return item

        async def audio(_):
            item.frames += 1

        async def finish(*, cancel=False):
            wire.current = None
            return None if cancel else final

        wire.begin, wire.audio, wire.finish = begin, audio, finish
        device = DigitalDevice()
        device.capture_time = time.monotonic()
        device.last_audible = 0 if near else device.capture_time
        device.playing.extend(b"\x00\x10" * 2400)
        with patch.dict("os.environ", {"ME3_VOICE_TTS": "kokoro"}):
            playback = Playback(None)
        playback.device = device
        playback.task = asyncio.create_task(asyncio.Event().wait())
        task = playback.task
        states = [VADState.SPEAKING] * 3 + [VADState.QUIET] * 155

        async def frames():
            for index in range(len(states)):
                if index == 1:
                    # Already silent at onset, before the final or SmartTurn decision.
                    self.assertTrue(device.paused)
                    self.assertEqual(device.render(480), b"")
                yield bytes(FRAME)
                await asyncio.sleep(0)

        try:
            with patch("me3.parakeet_voice.emit") as emit:
                await local_turns(wire, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)),
                                  AsyncMock(return_value=complete), playback)
            commits = [c.kwargs for c in emit.call_args_list if c.args == ("commit",)]
            return commits, task.cancelled(), bool(device.playing)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_short_stop_flushes_old_audio_even_if_overlap_and_smartturn_miss_it(self):
        for text, endpoint in [("Stop!", 100), ("stop", 0)]:
            with self.subTest(text=text):
                commits, cancelled, buffered = await self.play_turn(
                    text, text, near=False, complete=False, endpoint=endpoint)
                self.assertEqual([e.get("control") for e in commits], ["stop_speech"])
                self.assertTrue(cancelled)
                self.assertFalse(buffered)

    async def test_stop_fences_an_answer_already_replacing_a_feedback_cue(self):
        cancelling = asyncio.Event()

        async def cue():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await asyncio.Event().wait()

        with patch.dict("os.environ", {"ME3_VOICE_TTS": "kokoro"}):
            playback = Playback(None)
        playback.device = DigitalDevice()
        playback.speak = AsyncMock()
        playback.idle_output = True
        playback.receipt = "cue"
        playback.task = asyncio.create_task(cue())
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"op":"say","text":"old answer","epoch":0}\n')
        reader.feed_eof()
        loop = asyncio.get_running_loop()
        with (patch("me3.parakeet_voice.asyncio.StreamReader", return_value=reader),
              patch.object(loop, "connect_read_pipe", AsyncMock(return_value=(Mock(), None))),
              patch("me3.parakeet_voice.emit")):
            handler = asyncio.create_task(commands(playback))
            await asyncio.wait_for(cancelling.wait(), 2)
            await playback.cut()
            await handler
            await asyncio.sleep(0)
        playback.speak.assert_not_called()

    async def test_only_a_committed_deepgram_command_can_request_task_cancellation(self):
        for partial, final, near, provider, control in [
            ("stop", "Stop.", True, DeepgramStream, "stop_speech"),
            ("Stop current task.", "Stop current task.", True, DeepgramStream, "stop_current_task"),
            ("Please stop current task.", "Please stop current task.", True, DeepgramStream, "stop_current_task"),
            ("stop current task", "Stop.", True, DeepgramStream, "stop_speech"),
            ("stop current task", "Don't stop current task.", True, DeepgramStream, None),
            ("stop", "Explain the words stop current task.", True, DeepgramStream, None),
            ("stop", "Stop current tasks.", True, DeepgramStream, None),
            ("stop", "Stop current task.", False, DeepgramStream, "stop_speech"),
            ("stop", "Stop current task.", True, Stream, "stop_speech"),
        ]:
            with self.subTest(final=final, near=near, provider=provider.__name__):
                commits, _, _ = await self.play_turn(partial, final, near=near, provider=provider)
                self.assertEqual([(e["text"], e.get("control")) for e in commits], [(final, control)])
