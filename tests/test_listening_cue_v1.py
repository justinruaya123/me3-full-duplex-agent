import unittest


class ListeningCueTests(unittest.TestCase):
    def test_once_per_unfinished_turn_and_spaced_across_turns(self):
        from me3.parakeet_voice import ListeningCue
        cue = ListeningCue()
        words = "I was trying to work out how to explain"
        self.assertTrue(cue.offer("a", words, 160, now=100))
        self.assertFalse(cue.offer("a", words, 230, now=120))
        self.assertFalse(cue.offer("b", words, 165, now=104))
        self.assertTrue(cue.offer("b", words, 200, now=125))

    def test_sensitive_and_short_gaps_stay_quiet(self):
        from me3.parakeet_voice import ListeningCue
        cue = ListeningCue()
        for text in ("uh huh", "please type in the number 5281",
                     "the name is Ada Lovelace and then",
                     "I am spelling this out for you"):
            self.assertFalse(cue.offer("a", text, 180, now=100))
        self.assertFalse(cue.offer("a", "I want to tell you about it", 30, now=100))


class ConversationalFloorTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_turn_across_a_thinking_pause(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        words = "The point I was getting to was that"
        finished = words + " the room is already booked."
        states = ([VADState.SPEAKING] * 135 + [VADState.QUIET] * 68
                  + [VADState.SPEAKING] * 40 + [VADState.QUIET] * 40)
        wire = SimpleNamespace(current=None)

        async def begin():
            wire.current = SimpleNamespace(id="u", frames=0, text="")
            return wire.current

        async def audio(_):
            wire.current.frames += 1
            wire.current.text = "The point I was getting" if index < 166 else (
                words if index < 203 else finished)
            wire.current.finalized_frames = 0 if index < 166 else index + 1

        async def finish():
            text = wire.current.text
            wire.current = None
            return text

        index = 0
        async def frames():
            nonlocal index
            for index in range(len(states)):
                yield bytes(FRAME)
                await asyncio.sleep(0)

        wire.begin, wire.audio, wire.finish = begin, audio, finish
        playback = Mock(task=None, epoch=1, cut=AsyncMock(), allow_cue=True, last_reply_end=0.)
        playback.device.last_audible = playback.device.capture_time = 0.
        with patch("me3.parakeet_voice.emit") as emit:
            await local_turns(wire, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)),
                              AsyncMock(return_value=True), playback)
        commits = [c.kwargs["text"] for c in emit.call_args_list if c.args == ("commit",)]
        self.assertEqual(commits, [finished])
        self.assertTrue(playback.acknowledge.called)

    def test_standalone_receipts_and_clarifications(self):
        from me3.incremental import is_acknowledgment
        for text in ("I see.", "Ah, I see.", "Got it."):
            self.assertTrue(is_acknowledgment(text), text)
        for text in ("I see a problem.", "Got it wrong.", "I see?", "Huh?"):
            self.assertFalse(is_acknowledgment(text), text)

    def test_names_and_times_in_stories_are_allowed_and_dictation_stays_quiet(self):
        from me3.parakeet_voice import ListeningCue
        for text, expected in [
            ("When we met Lina after lunch we decided to", True),
            ("we left at 9 and wanted to", True),
            ("write these words exactly as I say them", False),
        ]:
            self.assertEqual(ListeningCue().offer("a", text, 160, now=40), expected)

    async def test_cached_cue_during_streaming_pause_before_endpoint_model_or_final(self):
        await self.check_streaming_cue("Could you put together a comparison of the", False)

    async def test_acoustic_continuation_can_cue_without_a_lexical_hint(self):
        await self.check_streaming_cue("We spent most of the afternoon together", True)

    async def check_streaming_cue(self, partial, acoustic):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        states = [VADState.SPEAKING] * 135 + [VADState.STOPPING] * 8 + [VADState.SPEAKING] * 5
        wire = SimpleNamespace(current=None)
        async def begin():
            wire.current = SimpleNamespace(id="u", frames=0, text="", finalized_frames=0)
            return wire.current
        async def audio(_):
            wire.current.frames += 1
            wire.current.text = partial
        async def frames():
            for _ in states:
                yield bytes(FRAME)
                await asyncio.sleep(0)
        wire.begin, wire.audio, wire.finish = begin, audio, AsyncMock()
        playback = Mock(task=None, epoch=1, allow_cue=True, last_reply_end=0.)
        playback.device.last_audible = playback.device.capture_time = 0.
        smart = AsyncMock(return_value=False)
        with patch("me3.parakeet_voice.emit") as emit:
            await local_turns(wire, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)), smart, playback)
        self.assertTrue(playback.acknowledge.called)
        self.assertEqual(smart.await_count, int(acoustic))
        wire.finish.assert_not_awaited()
        self.assertFalse(any(c.args == ("commit",) for c in emit.call_args_list))

    def test_cached_listener_skips_silent_lead_in_but_keeps_the_attack(self):
        from array import array
        from me3.parakeet_voice import trim_cue_lead
        quiet = array("h", [0]) * 12000
        speech = array("h", [-500, 600]) * 2400
        result = trim_cue_lead((quiet + speech).tobytes())
        self.assertEqual(result, quiet[:480].tobytes() + speech.tobytes())
        self.assertEqual(trim_cue_lead(speech.tobytes()), speech.tobytes())
