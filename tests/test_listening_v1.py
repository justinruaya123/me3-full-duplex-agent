"""Listening cues: control and fixture-transport checks, no inference."""

import asyncio
import importlib.util
import io
import os
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_duplex_v1 import Jobs

from me3.duplex import DuplexController
from me3.incremental import TranscriptRevision
from me3.ownership import OwnershipGate, SessionIngress, VoiceEvidence


class ListeningControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 100.0
        self.playing = False
        self.authorized = True
        self.spoken, self.stops, self.observed = [], [], []
        self.started, self.release, self.cancelled = (
            asyncio.Event(), asyncio.Event(), asyncio.Event(),
        )
        self.jobs = Jobs(Path(self.temp.name))
        self.job = self.jobs.submit("Keep this fixture job running")

        class Backend:
            calls = 0

            async def run(inner, *args, **kwargs):
                inner.calls += 1
                return "Fixture completed response."

        async def speak(text):
            self.spoken.append(text)
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            return True

        async def stop():
            self.stops.append(True)

        self.backend = Backend()
        self.controller = DuplexController(
            self.jobs, self.backend, speak, stop,
            clock=lambda: self.now,
            is_playing=lambda: self.playing,
            delivery_authorized=lambda: self.authorized,
            on_transcript=self.observed.append,
        )
        self.controller.focus = self.job["id"]
        self.gate = OwnershipGate("session", "fixture wake")
        self.ingress = SessionIngress(self.controller, self.gate)
        self.gate.wake("fixture wake")
        self.gate.begin_enrollment()
        self.gate.enroll("owner", duration=2, clean=True)
        self.evidence = VoiceEvidence("owner", True, True, False)
        self.controller.user_started()
        self.controller.user_stopped()

    async def asyncTearDown(self):
        self.release.set()
        await self.ingress.close()
        self.temp.cleanup()

    def event(self, text="I am still considering this, um.", *, revision=1,
              turn="turn", ended=True):
        return TranscriptRevision(
            "session", turn, revision, text, 0, 1,
            capture_ended=ended, non_acknowledgment_seen=True,
        )

    async def submit(self, event=None):
        return await self.ingress.accept(event or self.event(), self.evidence)

    async def settle(self):
        task = self.controller._active
        if task is not None:
            await asyncio.wait_for(asyncio.gather(
                task, return_exceptions=True,
            ), 1)

    def assert_no_authorization(self):
        self.assertFalse(self.controller.history)
        self.assertTrue(self.controller.turn_open)
        self.assertFalse(self.controller._turn_final.is_set())
        self.assertFalse(any(event.committed for event in self.observed))
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(self.controller.focus, self.job["id"])
        self.assertEqual(len(self.jobs.list()), 1)
        self.assertEqual(self.jobs.get(self.job["id"])["status"], "running")
        self.assertEqual(self.jobs.get(self.job["id"])["notified"], 0)

    async def test_safe_ended_provisional_speaks_only_neutral_cue(self):
        self.assertEqual(await self.submit(), "listening")
        await asyncio.wait_for(self.started.wait(), 1)
        self.assertEqual(self.spoken, ["Mm-hm."])
        self.assert_no_authorization()
        self.release.set()
        await self.settle()
        self.assert_no_authorization()

    async def test_cue_cooldown_is_six_seconds_across_revisions(self):
        self.assertEqual(await self.submit(), "listening")
        self.release.set()
        await self.settle()
        self.now += 5.999
        self.assertEqual(await self.submit(self.event(revision=2)), "hold")
        await asyncio.sleep(0)
        self.assertEqual(self.spoken, ["Mm-hm."])
        self.now = 106.0
        self.assertEqual(
            await self.submit(self.event(revision=3)), "listening",
        )
        await self.settle()
        self.assertEqual(self.spoken, ["Mm-hm.", "Mm-hm."])
        self.assert_no_authorization()

    async def test_sensitive_or_short_fragments_cannot_trigger_cue(self):
        fragments = (
            "I am thinking",  # Fewer than four words.
            "I am considering number 42 and",
            "The digits are one two three four, um.",
            "I am entering some Python code",
            "I was speaking with Alice about this",
            "I need a background task for this",
            "I approve this change so far",
            "Let me dictate the following words",
            "I am spelling this name aloud",
        )
        for revision, text in enumerate(fragments, 1):
            with self.subTest(text=text):
                self.assertEqual(await self.submit(self.event(
                    text, revision=revision,
                )), "hold")
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assert_no_authorization()

    async def test_partial_or_active_user_speech_cannot_trigger_delayed_cue(
        self,
    ):
        self.assertEqual(await self.submit(self.event(ended=False)), "hold")
        self.controller.user_started()
        self.assertEqual(await self.submit(self.event(revision=2)), "hold")
        self.controller.user_stopped()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assert_no_authorization()

    async def test_pending_question_or_existing_playback_suppresses_cue(self):
        self.controller.pending_question = True
        self.assertEqual(await self.submit(), "hold")
        self.controller.pending_question = False
        self.playing = True
        self.assertEqual(await self.submit(self.event(revision=2)), "hold")
        self.playing = False
        # A question being delivered is guarded before it enters history.
        self.controller._question_epoch = self.controller.epoch
        self.assertEqual(await self.submit(self.event(revision=3)), "hold")
        self.controller._question_epoch = None
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assert_no_authorization()

    async def test_busy_foreground_is_not_replaced_by_listening_cue(self):
        blocked = asyncio.Event()
        task = asyncio.create_task(blocked.wait())
        self.controller._active = task
        try:
            self.assertEqual(await self.submit(), "hold")
            self.assertIs(self.controller._active, task)
            self.assertFalse(task.cancelled())
            self.assertFalse(self.spoken)
            self.assert_no_authorization()
        finally:
            blocked.set()
            await task

    async def test_owner_addressing_and_delivery_authority_fail_closed(self):
        for evidence in (
            VoiceEvidence("other", True, True, False),
            VoiceEvidence("owner", False, True, False),
            VoiceEvidence("owner", True, None, False),
            VoiceEvidence("owner", True, False, False),
            VoiceEvidence("owner", True, True, True),
        ):
            with self.subTest(evidence=evidence):
                self.assertEqual(await self.ingress.accept(
                    self.event(), evidence,
                ), "unverified")
        self.authorized = False
        self.assertEqual(await self.submit(), "hold")
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assertEqual(self.backend.calls, 0)
        self.assertFalse(self.controller.history)

    async def test_onset_cancels_active_cue_and_flushes_without_job_change(
        self,
    ):
        self.assertEqual(await self.submit(), "listening")
        await asyncio.wait_for(self.started.wait(), 1)
        cue = self.controller._active
        self.controller.user_started()
        await asyncio.wait_for(self.cancelled.wait(), 1)
        await asyncio.wait_for(asyncio.gather(
            cue, return_exceptions=True,
        ), 1)
        for _ in range(20):
            if self.stops:
                break
            await asyncio.sleep(0)
        self.assertTrue(self.stops, "Cue onset cancellation must flush output")
        self.assertTrue(self.controller.user_speaking)
        self.assert_no_authorization()
        self.controller.user_stopped()
        self.release.set()
        await asyncio.sleep(0)
        self.assertEqual(self.spoken, ["Mm-hm."])

    async def test_onset_before_cue_task_runs_cannot_play_after_later_pause(
        self,
    ):
        self.assertEqual(await self.submit(), "listening")
        self.controller.user_started()
        self.controller.user_stopped()
        self.release.set()
        await self.settle()
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assert_no_authorization()

    async def test_close_before_cue_runs_and_stale_transcript_cannot_speak(
        self,
    ):
        self.assertEqual(await self.submit(), "listening")
        await self.ingress.close()
        self.release.set()
        await asyncio.sleep(0)
        self.assertFalse(self.spoken)
        self.assertEqual(await self.controller.transcript(
            self.event(revision=2), addressed=True,
        ), "stale")
        self.assertFalse(self.controller.history)

    async def test_revision_and_session_fences_prevent_duplicate_cues(self):
        event = self.event()
        self.assertEqual(await self.submit(event), "listening")
        self.release.set()
        await self.settle()
        self.now += 7
        self.assertEqual(await self.submit(event), "stale")
        self.assertEqual(await self.submit(replace(
            event, session_id="retired", revision=2,
        )), "stale")
        await asyncio.sleep(0)
        self.assertEqual(self.spoken, ["Mm-hm."])
        self.assert_no_authorization()


@unittest.skipUnless(
    importlib.util.find_spec("pipecat"),
    "Pipecat is not installed; listening fixture transport not run",
)
class ListeningPipelineTests(unittest.IsolatedAsyncioTestCase):
    """Real Pipecat processors with fixture inference and course owner bypass.

    This checks output scheduling and fences, not acoustics or voice identity.
    """

    async def test_pause_cue_then_resume_cannot_replay_old_cue_pcm(self):
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

        ready, cue_audio, reply_audio = (
            asyncio.Event(), asyncio.Event(), asyncio.Event(),
        )
        allow_tail, tail_waiting, tail_produced = (
            asyncio.Event(), asyncio.Event(), asyncio.Event(),
        )
        output, contexts, stages, recognized = [], [], [], []
        cue_pcm = b"\x01\x00" * 480
        obsolete_pcm = b"\x02\x00" * 480
        reply_pcm = b"\x03\x00" * 480
        first = b"\x04\x00" * 320
        more = b"\x05\x00" * 320

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
                    contexts.append(frame.context_id)
                    if frame.audio == cue_pcm:
                        cue_audio.set()
                    elif frame.audio == reply_pcm:
                        reply_audio.set()
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
                if text == "Mm-hm.":
                    yield cue_pcm
                    tail_waiting.set()
                    try:
                        await allow_tail.wait()
                    except asyncio.CancelledError:
                        await allow_tail.wait()
                    tail_produced.set()
                    yield obsolete_pcm
                else:
                    yield reply_pcm

            async def transcribe(self, audio):
                with wave.open(io.BytesIO(audio), "rb") as stream:
                    pcm = stream.readframes(stream.getnframes())
                recognized.append(pcm)
                return (
                    "I am still considering this, um." if pcm == first
                    else "I am still considering this, um. Explain the sky."
                )

        class Turn:
            async def __call__(self, pcm):
                return pcm == first + more

        class Foreground:
            calls = 0

            async def run(inner, *args, **kwargs):
                inner.calls += 1
                return "Fixture completed response."

        class Worker:
            async def run(self, *args, **kwargs):
                raise AssertionError("Provisional speech cannot create a job")

        transport, foreground = Transport(), Foreground()
        config = {
            "asr_base_url": "http://localhost/v1", "asr_model": "fixture",
            "tts_base_url": "http://localhost/v1", "tts_model": "fixture",
            "tts_voice": "fixture", "asr_key": "", "tts_key": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = AgentRuntime(root, Worker(), foreground)
            control = run_task = None
            try:
                with patch.dict(os.environ, {"ME3_AUDIO_MODE": "headphones"}):
                    run, control = await build(
                        transport, root, runtime=runtime, profile="course",
                        speech=Speech(), turn_analyzer=Turn(), config=config,
                        on_stage=lambda stage, **_: stages.append(stage),
                    )
                run_task = asyncio.create_task(run)
                await asyncio.wait_for(ready.wait(), 5)
                await transport.source.push_frame(
                    VADUserStartedSpeakingFrame(),
                )
                await transport.source.push_frame(InputAudioRawFrame(
                    first, sample_rate=16000, num_channels=1,
                ))
                await transport.source.push_frame(
                    VADUserStoppedSpeakingFrame(),
                )
                try:
                    await asyncio.wait_for(cue_audio.wait(), 1)
                except TimeoutError:
                    self.fail("Ended safe provisional capture sent no cue PCM")
                await asyncio.wait_for(tail_waiting.wait(), 1)
                self.assertEqual(output, [cue_pcm])
                self.assertEqual(stages, ["asr_partial"])
                self.assertFalse(control.controller.history)
                self.assertTrue(control.controller.turn_open)
                self.assertEqual(foreground.calls, 0)
                self.assertFalse(runtime.supervisor.list())
                await transport.source.push_frame(
                    VADUserStartedSpeakingFrame(),
                )
                for _ in range(100):
                    if control.controller.user_speaking:
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(control.controller.user_speaking)
                allow_tail.set()
                await asyncio.wait_for(tail_produced.wait(), 1)
                await transport.source.push_frame(InputAudioRawFrame(
                    more, sample_rate=16000, num_channels=1,
                ))
                await transport.source.push_frame(
                    VADUserStoppedSpeakingFrame(),
                )
                await asyncio.wait_for(reply_audio.wait(), 1)
                await asyncio.wait_for(asyncio.gather(
                    control.controller._active, return_exceptions=True,
                ), 1)
                self.assertEqual(output, [cue_pcm, reply_pcm])
                self.assertNotEqual(contexts[0], contexts[1])
                self.assertEqual(recognized, [first, first + more])
                self.assertEqual(stages, ["asr_partial", "asr_final"])
                self.assertEqual(foreground.calls, 1)
                self.assertEqual([item["role"] for item in
                                  control.controller.history],
                                 ["user", "assistant"])
                self.assertFalse(runtime.supervisor.list())
                self.assertIsNone(control.controller.focus)
            finally:
                allow_tail.set()
                if control is not None:
                    await asyncio.wait_for(control(), 5)
                if run_task is not None:
                    await asyncio.wait_for(asyncio.gather(
                        run_task, return_exceptions=True,
                    ), 5)
                await asyncio.wait_for(runtime.close(), 5)
