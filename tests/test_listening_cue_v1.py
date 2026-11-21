import unittest


class ListeningCueTests(unittest.TestCase):
    def test_standalone_wake_and_operator_override(self):
        from me3.bmo import wake_greeting
        for phrase in ["Hey BMO!", "Hey, Bimo.", "Hey Bee Mo", "BMO?", "ABMO?", "A b mo", "Abemo"]:
            self.assertTrue(wake_greeting(phrase, ""), phrase)
        for phrase in ["Hey BMO, find my note.", "Write down hey BMO.", "“Hey BMO”", "a memo"]:
            self.assertFalse(wake_greeting(phrase, ""), phrase)
        self.assertTrue(wake_greeting("Hey Mira.", "Hey Mira"))
        self.assertFalse(wake_greeting("BMO?", "Hey Mira"))
        self.assertFalse(wake_greeting("BMO.", bare=False))
        self.assertTrue(wake_greeting("Hey, BMO.", "   ", bare=False))

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

    def test_dangling_disfluency_does_not_close_a_request(self):
        from me3.parakeet_voice import unfinished_clause
        for partial in ["Please put this in the, um.", "Please add the th-", "What I wanted was…"]:
            self.assertTrue(unfinished_clause(partial))
        self.assertFalse(unfinished_clause("I, I meant the other folder."))


class ConversationalFloorTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_resumed_speech_after_wake_needs_a_new_provider_final(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.deepgram import DeepgramStream
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        wake, request = "Hey, Beemo.", "Hey, Beemo. Stop."
        states = ([VADState.SPEAKING] * 30 + [VADState.QUIET] * 3
                  + [VADState.SPEAKING] * 5 + [VADState.QUIET] * 45)
        stream = Mock(spec=DeepgramStream, current=None)
        turn = SimpleNamespace(id="u", frames=0, text=wake, settled_text=wake,
                               finalized_frames=30, endpoint_frames=30)
        async def begin():
            stream.current = turn
            return turn
        async def audio(_):
            turn.frames += 1
        def finish(text):
            stream.current = None
            return text
        stream.begin, stream.audio = begin, audio
        stream.finish_endpoint.side_effect = lambda: finish(wake)
        stream.finish = AsyncMock(side_effect=lambda: finish(request))
        async def frames():
            for _ in states:
                yield bytes(FRAME)
                await asyncio.sleep(0)
        playback = Mock(device=None, overlap=False, task=None, awaiting_answer=False,
                        allow_cue=False, epoch=1, cut=AsyncMock())
        with patch("me3.parakeet_voice.emit") as emit:
            await local_turns(stream, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)),
                              AsyncMock(return_value=True), playback)
        self.assertEqual([c.kwargs["text"] for c in emit.call_args_list if c.args == ("commit",)], [request])

    async def test_completed_first_sentence_can_receive_a_spoken_qualifier(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        first = "Plan a walking route."
        full = first + " Start at the park."
        states = ([VADState.SPEAKING] * 60 + [VADState.QUIET] * 28
                  + [VADState.SPEAKING] * 35 + [VADState.QUIET] * 55)
        wire = SimpleNamespace(current=None)
        async def begin():
            wire.current = SimpleNamespace(id=str(index), frames=0, text="", settled_text="")
            return wire.current
        async def audio(_):
            u = wire.current
            u.frames += 1
            u.text = u.settled_text = first if index < 88 else full
            u.finalized_frames = u.frames
        async def finish():
            text = wire.current.text
            wire.current = None
            return text
        async def frames():
            nonlocal index
            for index in range(len(states)):
                yield bytes(FRAME)
                await asyncio.sleep(0)
        index = 0
        wire.begin, wire.audio, wire.finish = begin, audio, finish
        playback = Mock(device=None, task=None, epoch=1, cut=AsyncMock(), allow_cue=False)
        with patch("me3.parakeet_voice.emit") as emit:
            await local_turns(wire, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)),
                              AsyncMock(return_value=True), playback)
        self.assertEqual([c.kwargs["text"] for c in emit.call_args_list if c.args == ("commit",)], [full])

    async def test_settled_sentence_can_recover_an_acoustic_miss(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        sentence = "Please bring the blue folder."
        plain = sentence.rstrip(".")
        for settled, partial, coverage, endpoint, final, expected in [
            (sentence, sentence, 90, 0, sentence, [sentence]),
            (plain, plain, 90, 90, plain, [plain]),
            (plain, plain, 90, 40, plain, []),
            (sentence, sentence, 10, 0, sentence, []),
            ("", sentence, 90, 90, sentence, []),
            (sentence, sentence + " And", 90, 0, sentence, []),
            (sentence, sentence, 90, 0, "Please bring", []),
            ("We still need the.", "We still need the.", 90, 90, "We still need the.", []),
        ]:
            with self.subTest(settled=settled, partial=partial, coverage=coverage, final=final):
                item = SimpleNamespace(id="x", frames=0, settled_text=settled,
                                       text=partial, finalized_frames=coverage, endpoint_frames=endpoint)
                stream = SimpleNamespace(current=None)
                async def begin():
                    stream.current = item
                    return item
                async def audio(_):
                    item.frames += 1
                async def finish(*, cancel=False):
                    stream.current = None
                    return None if cancel else final
                stream.begin, stream.audio, stream.finish = begin, audio, finish
                states = [VADState.SPEAKING] * 100 + [VADState.QUIET] * 90
                async def frames():
                    for _ in states:
                        yield bytes(FRAME)
                        await asyncio.sleep(0)
                playback = Mock(device=None, overlap=False, task=None, allow_cue=False,
                                awaiting_answer=False, epoch=1, cut=AsyncMock())
                with patch("me3.parakeet_voice.emit") as emit:
                    await local_turns(stream, frames(), Mock(analyze_audio=AsyncMock(side_effect=states)),
                                      AsyncMock(return_value=False), playback)
                self.assertEqual([c.kwargs["text"] for c in emit.call_args_list if c.args == ("commit",)], expected)

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
            wire.current = SimpleNamespace(id="u", frames=0, text="", revision=0)
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
        playback = Mock(task=None, epoch=1, cut=AsyncMock(), allow_cue=True, overlap=True, last_reply_end=0.)
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
            wire.current = SimpleNamespace(id="u", frames=0, text="", finalized_frames=0, revision=0)
            return wire.current
        async def audio(_):
            wire.current.frames += 1
            wire.current.text = partial
        async def frames():
            for _ in states:
                yield bytes(FRAME)
                await asyncio.sleep(0)
        wire.begin, wire.audio, wire.finish = begin, audio, AsyncMock()
        playback = Mock(task=None, epoch=1, allow_cue=True, overlap=True, last_reply_end=0.)
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
        from me3.bmo import trim_lead
        quiet = array("h", [0]) * 12000
        speech = array("h", [-500, 600]) * 2400
        result = trim_lead((quiet + speech).tobytes())
        self.assertEqual(result, quiet[:480].tobytes() + speech.tobytes())
        self.assertEqual(trim_lead(speech.tobytes()), speech.tobytes())
