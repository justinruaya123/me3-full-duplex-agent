"""Floor-only acknowledgments: pure control/capture checks, no inference.

Development phrases are independent of benchmark clips. An ended VAD capture
is not a semantic commit, user authorization, or permission to execute tools.
"""

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_duplex_v1 import Jobs

from me3.capture import RollingCapture
from me3.duplex import DuplexController, classify_overlap
from me3.incremental import RollingTranscript, TranscriptRevision
from me3.ownership import OwnershipGate, SessionIngress, VoiceEvidence


class PureAcknowledgmentPolicyTests(unittest.TestCase):
    def test_whole_ack_units_are_bounded_and_never_match_a_prefix(self):
        affirmative = (
            "right okay", "Yeah, right, okay!", "Mm-hmm. Okay.",
            "uh-huh yes", "yes ok right", "okay sure", "sure right",
        )
        other = (
            "right okay please", "right no", "no okay", "yes but",
            "yes cancel job 1", "right okay yes okay", "not okay",
            "right maybe", "thanks", "yes /preview 1", "right nothing",
            "sure but stop", "sure cancel job",
        )
        for text in affirmative:
            with self.subTest(text=text):
                self.assertEqual(
                    classify_overlap(text, True, addressed=True),
                    "backchannel",
                )
        for text in other:
            with self.subTest(text=text):
                self.assertEqual(
                    classify_overlap(text, True, addressed=True), "turn",
                )

    def test_capture_end_is_optional_and_independent_of_semantic_commit(self):
        original = TranscriptRevision("s", "t", 1, "okay", 0, 1)
        self.assertFalse(original.capture_ended)
        rolling = RollingTranscript("s", "t")
        ended = rolling.update("right okay", 0, 1, capture_ended=True)
        self.assertTrue(ended.capture_ended)
        self.assertFalse(ended.committed)
        self.assertFalse(ended.non_acknowledgment_seen)
        self.assertFalse(rolling.closed)

    def test_all_asr_hypotheses_can_only_veto_floor_relaxation(self):
        rolling = RollingTranscript("s", "t")
        rolling.update("please wait while I explain", 0, 1)
        ended = rolling.update("right okay", 0, 2, capture_ended=True)
        self.assertTrue(ended.non_acknowledgment_seen)
        self.assertFalse(ended.committed)


class PurePausedControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = Jobs(Path(self.temp.name))
        self.job = self.jobs.submit("Keep delegated work running")
        self.speech_started = asyncio.Event()
        self.release_speech = asyncio.Event()
        self.playing = self.authorized = True
        self.stops = 0
        self.observed = []

        class Backend:
            calls = 0
            answer = "An independent development explanation."

            async def run(inner, *args, **kwargs):
                inner.calls += 1
                return inner.answer

        async def speak(text):
            self.speech_started.set()
            await self.release_speech.wait()
            return True

        async def stop():
            self.stops += 1

        self.backend = Backend()
        self.controller = DuplexController(
            self.jobs, self.backend, speak, stop,
            is_playing=lambda: self.playing,
            delivery_authorized=lambda: self.authorized,
            on_transcript=self.observed.append,
        )
        self.gate = OwnershipGate("session", "development wake")
        self.ingress = SessionIngress(self.controller, self.gate)
        await self.controller.accept("Explain the development example.")
        await asyncio.wait_for(self.speech_started.wait(), 1)
        self.before_history = list(self.controller.history)
        self.before_epoch = self.controller.epoch
        self.before_stops = self.stops
        self.old_task = self.controller._active
        self.controller.user_started()
        self.controller.user_stopped()

    async def asyncTearDown(self):
        self.release_speech.set()
        await self.controller.close()
        self.temp.cleanup()

    def event(self, text="right okay", *, revision=1, ended=True,
              turn="turn", session="session", committed=False,
              non_ack=False):
        return TranscriptRevision(
            session, turn, revision, text, 0, 1, committed=committed,
            capture_ended=ended, non_acknowledgment_seen=non_ack,
        )

    def assert_no_authorization(self):
        self.assertEqual(self.backend.calls, 1)
        self.assertEqual(self.stops, self.before_stops)
        self.assertEqual(self.controller.epoch, self.before_epoch)
        self.assertEqual(self.controller.history, self.before_history)
        self.assertIs(self.controller._active, self.old_task)
        self.assertTrue(self.controller.busy)
        self.assertIsNone(self.controller.focus)
        self.assertEqual(self.jobs.get(self.job["id"])["status"], "running")
        self.assertEqual(self.jobs.get(self.job["id"])["notified"], 0)
        self.assertEqual(len(self.jobs.list()), 1)
        self.assertFalse(any(event.committed for event in self.observed))

    async def test_ended_ack_releases_only_floor_and_consumes_later_revisions(
        self,
    ):
        result = await self.controller.transcript(self.event(), addressed=True)
        self.assertEqual(result, "backchannel")
        self.assertFalse(self.controller.turn_open)
        self.assertTrue(self.controller._turn_final.is_set())
        self.assertFalse(self.controller.poll())
        self.assert_no_authorization()
        late = self.event(
            "background task execute a late request", revision=2,
            committed=True,
        )
        self.assertEqual(
            await self.controller.transcript(late, addressed=True), "stale",
        )
        self.assertEqual(len(self.observed), 1)
        self.assert_no_authorization()

    async def test_ongoing_ack_hypothesis_keeps_pause(self):
        self.assertEqual(await self.controller.transcript(
            self.event(ended=False), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.turn_open)
        self.assertFalse(self.controller._turn_final.is_set())
        self.assert_no_authorization()

    async def test_pending_question_yes_cannot_approve_or_resolve_floor(self):
        self.controller.pending_question = True
        self.assertEqual(await self.controller.transcript(
            self.event("yes"), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.pending_question)
        self.assertTrue(self.controller.turn_open)
        self.assert_no_authorization()

    async def start_question(self):
        self.backend.answer = "Would you like the details?"
        self.speech_started.clear()
        await self.controller.accept("Ask a development question.")
        await asyncio.wait_for(self.speech_started.wait(), 1)
        self.assertFalse(self.controller.pending_question)
        self.assertTrue(self.controller.busy)
        self.assertTrue(self.controller._speaking)
        self.assertFalse(any(
            item["role"] == "assistant" and item["content"].endswith("?")
            for item in self.controller.history
        ))

    async def test_delivering_question_holds_answer_until_semantic_commit(
        self,
    ):
        await self.start_question()
        epoch, history = self.controller.epoch, list(self.controller.history)
        self.assertEqual(await self.controller.transcript(
            self.event("yes"), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.turn_open)
        self.assertEqual(self.controller.epoch, epoch)
        self.assertEqual(self.controller.history, history)
        self.assertEqual(self.backend.calls, 2)
        self.assertEqual(await self.controller.transcript(
            self.event("yes", revision=2, committed=True), addressed=True,
        ), "turn")
        self.assertEqual(self.controller.history[-1],
                         {"role": "user", "content": "yes"})
        self.assertEqual(self.controller.epoch, epoch + 1)

    async def test_early_committed_answer_to_delivering_question_is_a_turn(
        self,
    ):
        await self.start_question()
        epoch = self.controller.epoch
        self.assertEqual(await self.controller.transcript(
            self.event("yes", committed=True), addressed=True,
        ), "turn")
        self.assertEqual(self.controller.history[-1],
                         {"role": "user", "content": "yes"})
        self.assertEqual(self.controller.epoch, epoch + 1)
        self.assertFalse(any(
            item["role"] == "assistant" and item["content"].endswith("?")
            for item in self.controller.history
        ))

    async def test_old_question_cleanup_cannot_clear_current_question_guard(
        self,
    ):
        first_started, second_started = asyncio.Event(), asyncio.Event()
        release_old = asyncio.Event()

        async def stubborn_speech(text):
            if text == "First development question?":
                first_started.set()
                try:
                    await release_old.wait()
                except asyncio.CancelledError:
                    await release_old.wait()
            else:
                second_started.set()
                await self.release_speech.wait()
            return False

        self.controller.speak = stubborn_speech
        self.backend.answer = "First development question?"
        old = None
        try:
            await self.controller.accept("Ask the first question")
            await asyncio.wait_for(first_started.wait(), 1)
            old = self.controller._active
            self.backend.answer = "Second development question?"
            await self.controller.accept("Ask the next question")
            await asyncio.wait_for(second_started.wait(), 1)
            epoch = self.controller.epoch
            release_old.set()
            await asyncio.wait_for(asyncio.shield(old), 1)
            self.assertEqual(await self.controller.transcript(
                self.event("yes"), addressed=True,
            ), "hold")
            self.assertEqual(self.controller.epoch, epoch)
            self.controller.pending_question = True
            await self.controller.accept("stop talking", addressed=True)
            self.assertTrue(self.controller.pending_question)
            self.assertFalse(any(item["role"] == "assistant"
                                 for item in self.controller.history))
        finally:
            release_old.set()
            if old is not None:
                await asyncio.wait_for(asyncio.gather(
                    old, return_exceptions=True,
                ), 1)

    async def test_prior_non_ack_cannot_be_erased_by_false_metadata(self):
        self.assertEqual(await self.controller.transcript(
            self.event("please wait", ended=False), addressed=True,
        ), "hold")
        self.assertEqual(await self.controller.transcript(
            self.event(revision=2, non_ack=False), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.turn_open)
        self.assert_no_authorization()

    async def test_capture_non_ack_bit_blocks_unobserved_prior_hypothesis(
        self,
    ):
        self.assertEqual(await self.controller.transcript(
            self.event(non_ack=True), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.turn_open)
        self.assert_no_authorization()

    async def test_negative_or_unknown_addressing_never_relaxes_pause(self):
        for index, addressed in enumerate((False, None, 1), 1):
            with self.subTest(addressed=addressed):
                self.assertEqual(await self.controller.transcript(
                    self.event(turn=str(index)), addressed=addressed,
                ), "hold")
                self.assertTrue(self.controller.turn_open)
                self.assert_no_authorization()

    async def test_no_confirmed_old_playback_or_delivery_rights_keeps_pause(
        self,
    ):
        self.playing = False
        self.assertEqual(await self.controller.transcript(
            self.event(turn="not-playing"), addressed=True,
        ), "hold")
        self.playing = True
        self.controller.is_playing = None
        self.assertEqual(await self.controller.transcript(
            self.event(turn="no-receipt"), addressed=True,
        ), "hold")
        self.controller.is_playing = lambda: True
        self.authorized = False
        self.assertEqual(await self.controller.transcript(
            self.event(turn="unauthorized"), addressed=True,
        ), "hold")
        self.assert_no_authorization()

    async def test_stale_playback_hint_without_active_speech_keeps_pause(self):
        self.release_speech.set()
        await asyncio.wait_for(asyncio.shield(self.old_task), 1)
        history = list(self.controller.history)
        self.assertFalse(self.controller.busy)
        self.assertEqual(await self.controller.transcript(
            self.event(), addressed=True,
        ), "hold")
        self.assertTrue(self.controller.turn_open)
        self.assertEqual(self.controller.history, history)
        self.assertEqual(self.controller.epoch, self.before_epoch)
        self.assertEqual(self.backend.calls, 1)

    async def test_ongoing_speech_and_stale_session_or_revision_cannot_resolve(
        self,
    ):
        self.controller.user_started()
        self.assertEqual(await self.controller.transcript(
            self.event(revision=2), addressed=True,
        ), "hold")
        self.controller.user_stopped()
        self.assertEqual(await self.controller.transcript(
            self.event(revision=1), addressed=True,
        ), "stale")
        self.assertEqual(await self.controller.transcript(
            self.event(session="old-session", revision=3), addressed=True,
        ), "stale")
        self.assertTrue(self.controller.turn_open)
        self.assert_no_authorization()

    async def test_unverified_owner_ack_cannot_relax_floor(self):
        self.gate.wake("development wake")
        self.gate.begin_enrollment()
        self.gate.enroll("alice", duration=3, clean=True)
        for revision, evidence in enumerate((
            VoiceEvidence("alice", False, True, False),
            VoiceEvidence("bob", True, True, False),
            VoiceEvidence("alice", True, None, False),
            VoiceEvidence("alice", True, True, True),
        ), 1):
            self.assertEqual(await self.ingress.accept(
                self.event(revision=revision), evidence,
            ), "unverified")
        self.assertTrue(self.controller.turn_open)
        self.assert_no_authorization()

    async def test_closed_controller_cannot_relax_or_record_late_ack(self):
        await self.controller.close()
        epoch = self.controller.epoch
        self.assertEqual(await self.controller.transcript(
            self.event(), addressed=True,
        ), "stale")
        self.assertEqual(self.controller.epoch, epoch)
        self.assertFalse(self.observed)


class PureCaptureBackchannelTests(unittest.IsolatedAsyncioTestCase):
    def capture(self, texts):
        self.events, self.empty = [], []
        values = iter(texts)

        async def recognize(pcm):
            return next(values)

        async def analyze(pcm):
            return False

        async def emit(event, pcm):
            self.events.append(event)

        return RollingCapture(
            "session", recognize, analyze, emit, on_empty=self.empty.append,
        )

    async def test_final_flags_do_not_commit_and_consumption_starts_fresh(
        self,
    ):
        capture = self.capture([
            "right okay", "a separate development request",
        ])
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            generation = capture.generation
            await capture.finish(generation=generation)
            event = self.events[-1]
            self.assertTrue(event.capture_ended)
            self.assertFalse(event.committed)
            self.assertTrue(capture.consume_backchannel(
                event, generation=generation,
            ))
            self.assertGreater(capture.generation, generation)
            self.assertFalse(capture.committed)
            self.assertIsNone(capture.rolling)
            self.assertFalse(capture.audio)
            self.assertFalse(capture.preroll)
            self.assertFalse(self.empty)
            capture.begin()
            capture.feed(b"\x02\x00" * 320)
            await capture.finish(generation=capture.generation)
            self.assertNotEqual(self.events[-1].turn_id, event.turn_id)
            self.assertTrue(self.events[-1].non_acknowledgment_seen)
            self.assertFalse(any(item.committed for item in self.events))
        finally:
            await capture.close()

    async def test_partial_has_no_capture_end_and_prior_non_ack_persists(self):
        capture = self.capture(["wait for the complete request", "right okay"])
        try:
            capture.begin()
            capture.feed(bytes(32000))
            await capture._partial
            self.assertFalse(self.events[0].capture_ended)
            capture.feed(b"\x01\x00" * 320)
            generation = capture.generation
            await capture.finish(generation=generation)
            ended = self.events[-1]
            self.assertTrue(ended.capture_ended)
            self.assertTrue(ended.non_acknowledgment_seen)
            self.assertFalse(capture.consume_backchannel(
                ended, generation=generation,
            ))
            self.assertEqual(capture.generation, generation)
            self.assertFalse(any(item.committed for item in self.events))
        finally:
            await capture.close()

    async def test_consume_rejects_stale_revision_session_generation_and_close(
        self,
    ):
        capture = self.capture(["right okay"])
        try:
            capture.begin()
            capture.feed(bytes(640))
            generation = capture.generation
            await capture.finish(generation=generation)
            event = self.events[-1]
            bad = (
                replace(event, session_id="old-session"),
                replace(event, turn_id="old-turn"),
                replace(event, revision=event.revision + 1),
                replace(event, capture_ended=False),
                replace(event, committed=True),
                replace(event, text="cancel job 1"),
                replace(event, non_acknowledgment_seen=True),
            )
            for value in bad:
                self.assertFalse(capture.consume_backchannel(
                    value, generation=generation,
                ))
            self.assertFalse(capture.consume_backchannel(
                event, generation=generation - 1,
            ))
            capture.begin()
            self.assertFalse(capture.consume_backchannel(
                event, generation=generation,
            ))
            await capture.close()
            self.assertFalse(capture.consume_backchannel(
                event, generation=capture.generation,
            ))
        finally:
            await capture.close()

    async def test_consumption_preserves_only_post_capture_preroll(self):
        capture = self.capture(["right okay"])
        try:
            capture.begin()
            capture.feed(b"\x01\x00" * 320)
            generation = capture.generation
            await capture.finish(generation=generation)
            newer = b"\x02\x00" * 160
            capture.feed(newer)
            self.assertTrue(capture.consume_backchannel(
                self.events[-1], generation=generation,
            ))
            capture.begin()
            self.assertEqual(bytes(capture.audio), newer)
        finally:
            await capture.close()


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; retained PCM integration not run",
)
class PausedBackchannelPipelineTests(unittest.IsolatedAsyncioTestCase):
    """Actual Pipecat scheduling; all ASR/TTS/LLM/worker output is a fixture.

    This class initializes the installed CPU VAD when selected. Pure tests can
    be selected with ``-k Pure`` without importing audio/native code.
    """

    async def exercise(self, operation):
        from pipecat.frames.frames import (
            InputAudioRawFrame,
            StartFrame,
            TTSAudioRawFrame,
            TTSStartedFrame,
            VADUserStartedSpeakingFrame,
            VADUserStoppedSpeakingFrame,
        )
        from pipecat.processors.frame_processor import FrameProcessor

        from me3.audio_pipeline import build
        from me3.runtime import AgentRuntime

        ready, first_audio = asyncio.Event(), asyncio.Event()
        tts_started, allow_first = asyncio.Event(), asyncio.Event()
        allow_second, second_produced = asyncio.Event(), asyncio.Event()
        second_audio, asr_started = asyncio.Event(), asyncio.Event()
        release_asr, asr_returned = asyncio.Event(), asyncio.Event()
        job_started, release_job = asyncio.Event(), asyncio.Event()
        job_cancelled = asyncio.Event()
        output, stages, contexts = [], [], []
        first_pcm = b"\x01\x00" * 480
        retained_pcm = b"\x02\x00" * 480
        recognition_task = None
        if operation != "slow_first_pcm":
            allow_first.set()

        class Source(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, StartFrame):
                    ready.set()
                await self.push_frame(frame, direction)

        class Sink(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, TTSStartedFrame):
                    tts_started.set()
                if isinstance(frame, TTSAudioRawFrame):
                    output.append(frame.audio)
                    contexts.append(frame.context_id)
                    if frame.audio == first_pcm:
                        first_audio.set()
                    elif frame.audio == retained_pcm:
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
                await allow_first.wait()
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
                    await release_asr.wait()
                asr_returned.set()
                return "right okay"

        class Turn:
            async def __call__(self, pcm):
                return False

        class Foreground:
            calls = 0

            async def run(self, *args, **kwargs):
                self.calls += 1
                return "An independent development explanation."

        class Worker:
            async def run(self, *args, **kwargs):
                job_started.set()
                try:
                    await release_job.wait()
                except asyncio.CancelledError:
                    job_cancelled.set()
                    raise
                return "A fixture delegated result."

        transport, foreground = Transport(), Foreground()
        config = {
            "asr_base_url": "http://localhost/v1", "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1", "tts_model": "fixture",
            "tts_voice": "fixture", "asr_key": "", "tts_key": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = AgentRuntime(root, Worker(), foreground)
            run_task = control = lifecycle = job = None
            close_invoked = False
            try:
                with patch.dict(os.environ, {"ME3_AUDIO_MODE": "headphones"}):
                    run, control = await build(
                        transport, root, runtime=runtime, profile="course",
                        speech=Speech(), turn_analyzer=Turn(), config=config,
                        on_stage=lambda stage, **_: stages.append(stage),
                    )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                job = control.controller.jobs.submit("Blocked fixture work")
                await asyncio.wait_for(job_started.wait(), 1)
                await control.controller.accept("Explain the development case")
                await asyncio.wait_for(tts_started.wait(), 1)
                if operation != "slow_first_pcm":
                    await asyncio.wait_for(first_audio.wait(), 1)
                    for _ in range(100):
                        if control.controller.is_playing():
                            break
                        await asyncio.sleep(0.005)
                    self.assertTrue(control.controller.is_playing())
                epoch = control.controller.epoch
                users = [item for item in control.controller.history
                         if item["role"] == "user"]
                await transport.source.push_frame(
                    VADUserStartedSpeakingFrame(),
                )
                for _ in range(100):
                    if control.controller.user_speaking:
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(control.controller.user_speaking)
                allow_second.set()
                if operation != "slow_first_pcm":
                    await asyncio.wait_for(second_produced.wait(), 1)
                await asyncio.sleep(0.05)
                self.assertEqual(
                    output, [] if operation == "slow_first_pcm"
                    else [first_pcm],
                )
                await transport.source.push_frame(InputAudioRawFrame(
                    b"\0" * 640, sample_rate=16000, num_channels=1,
                ))
                await transport.source.push_frame(
                    VADUserStoppedSpeakingFrame(),
                )
                await asyncio.wait_for(asr_started.wait(), 1)
                if operation == "new_generation":
                    await transport.source.push_frame(
                        VADUserStartedSpeakingFrame(),
                    )
                    for _ in range(100):
                        if control.controller.user_speaking:
                            break
                        await asyncio.sleep(0.005)
                    self.assertTrue(control.controller.user_speaking)
                elif operation in {"mute", "close"}:
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
                release_asr.set()
                await asyncio.wait_for(asr_returned.wait(), 1)
                if recognition_task is not None:
                    await asyncio.wait_for(asyncio.gather(
                        recognition_task, return_exceptions=True,
                    ), 1)
                if lifecycle is not None:
                    await asyncio.wait_for(lifecycle, 5)
                if operation == "resume":
                    await asyncio.wait_for(second_audio.wait(), 1)
                    self.assertEqual(output, [first_pcm, retained_pcm])
                    self.assertIsNotNone(contexts[0])
                    self.assertEqual(contexts, [contexts[0], contexts[0]])
                    self.assertEqual(control.controller.epoch, epoch)
                    self.assertEqual(stages, ["asr_partial"])
                else:
                    if operation == "close":
                        await asyncio.wait_for(run_task, 5)
                    else:
                        await asyncio.sleep(0.05)
                    self.assertFalse(second_audio.is_set())
                    self.assertEqual(
                        output, [] if operation == "slow_first_pcm"
                        else [first_pcm],
                    )
                    if operation == "slow_first_pcm":
                        self.assertTrue(control.controller.turn_open)
                        self.assertFalse(
                            control.controller._turn_final.is_set(),
                        )
                        self.assertFalse(control.controller.is_playing())
                        self.assertEqual(control.controller.epoch, epoch)
                    if operation == "new_generation":
                        self.assertTrue(control.controller.user_speaking)
                        self.assertTrue(control.controller.turn_open)
                        self.assertEqual(control.controller.epoch, epoch)
                self.assertNotIn("asr_final", stages)
                self.assertEqual(foreground.calls, 1)
                self.assertEqual(users, [
                    item for item in control.controller.history
                    if item["role"] == "user"
                ])
                self.assertIsNone(control.controller.focus)
                self.assertFalse(job_cancelled.is_set())
                self.assertFalse(runtime.closed)
                self.assertEqual(len(runtime.supervisor.list()), 1)
                record = runtime.supervisor.get(job["id"])
                self.assertEqual(record["status"], "running")
                self.assertEqual(record["revision"], 1)
                self.assertEqual(record["notified"], 0)
                events = [json.loads(line) for line in
                          (root / "events.jsonl").read_text().splitlines()]
                self.assertFalse(any(
                    event["event"] == "transcript_revision"
                    and event["committed"] for event in events
                ))
                resumes = sum(event["event"] ==
                              "provisional_backchannel_resumed"
                              for event in events)
                self.assertEqual(resumes, int(operation == "resume"))
            finally:
                allow_first.set()
                allow_second.set()
                release_asr.set()
                release_job.set()
                try:
                    if lifecycle is not None:
                        await asyncio.wait_for(asyncio.gather(
                            lifecycle, return_exceptions=True,
                        ), 5)
                    if control is not None and not close_invoked:
                        await asyncio.wait_for(control(), 5)
                    if run_task is not None:
                        await asyncio.wait_for(asyncio.gather(
                            run_task, return_exceptions=True,
                        ), 5)
                    if job is not None:
                        await asyncio.wait_for(
                            runtime.supervisor.wait(job["id"]), 1,
                        )
                finally:
                    await asyncio.wait_for(runtime.close(), 5)

    async def test_retained_pcm_resumes_same_epoch_without_commit_or_action(
        self,
    ):
        await self.exercise("resume")

    async def test_tts_start_without_received_pcm_cannot_consume_ack(self):
        await self.exercise("slow_first_pcm")

    async def test_new_capture_generation_rejects_late_ack_floor_resolution(
        self,
    ):
        await self.exercise("new_generation")

    async def test_mute_rejects_late_ack_and_preserves_delegated_work(self):
        await self.exercise("mute")

    async def test_close_rejects_late_ack_and_preserves_delegated_work(self):
        await self.exercise("close")


if __name__ == "__main__":
    unittest.main()
