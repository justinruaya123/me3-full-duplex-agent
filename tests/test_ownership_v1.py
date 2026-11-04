"""Ownership is explicit evidence, never inferred from wake or VAD."""

import tempfile
import unittest
from pathlib import Path

from test_duplex_v1 import Backend, Jobs

from me3.duplex import DuplexController
from me3.incremental import TranscriptRevision


class OwnershipTests(unittest.TestCase):
    def test_wake_is_not_identity_and_enrollment_is_deliberate(self):
        from me3.ownership import OwnershipGate, VoiceEvidence

        gate = OwnershipGate("session", "hello agent")
        self.assertTrue(gate.wake("hello agent"))
        evidence = VoiceEvidence("alice", True, True, False)
        self.assertFalse(gate.authorize(evidence))
        with self.assertRaises(RuntimeError):
            gate.enroll("alice", duration=3, clean=True)
        gate.begin_enrollment()
        with self.assertRaises(ValueError):
            gate.enroll("alice", duration=0.3, clean=True)
        gate.enroll("alice", duration=3, clean=True)
        self.assertTrue(gate.authorize(evidence))
        self.assertFalse(gate.wake("hello agent"))
        self.assertEqual(gate.owner, "alice")

    def test_unknown_mixed_nonowner_and_side_talk_cannot_authorize(self):
        from me3.ownership import OwnershipGate, VoiceEvidence

        gate = OwnershipGate("session", "hello agent")
        gate.wake("hello agent")
        gate.begin_enrollment()
        gate.enroll("alice", duration=3, clean=True)
        for evidence in (
            VoiceEvidence("bob", True, True, False),
            VoiceEvidence("alice", False, True, False),
            VoiceEvidence("alice", True, None, False),
            VoiceEvidence("alice", True, False, False),
            VoiceEvidence("alice", True, True, True),
            VoiceEvidence("alice", True, True, None),
        ):
            self.assertFalse(gate.authorize(evidence))
        gate.close()
        self.assertIsNone(gate.owner)
        self.assertFalse(
            gate.authorize(VoiceEvidence("alice", True, True, False))
        )

    def test_timeout_and_mute_revoke_authority(self):
        from me3.ownership import OwnershipGate, VoiceEvidence

        now = [0.0]
        gate = OwnershipGate(
            "session", "wake", clock=lambda: now[0], timeout=10
        )
        gate.wake("wake")
        gate.begin_enrollment()
        gate.enroll("alice", duration=3, clean=True)
        now[0] = 11
        self.assertFalse(
            gate.authorize(VoiceEvidence("alice", True, True, False))
        )
        self.assertIsNone(gate.owner)


class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_session_or_unverified_commit_cannot_delegate(self):
        from me3.ownership import OwnershipGate, SessionIngress, VoiceEvidence

        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(Path(directory))
            spoken = []

            async def speak(text):
                spoken.append(text)
                return True

            async def stop():
                pass

            controller = DuplexController(jobs, Backend(), speak, stop)
            gate = OwnershipGate("new-session", "wake")
            ingress = SessionIngress(controller, gate)
            try:
                event = TranscriptRevision(
                    "new-session",
                    "turn",
                    1,
                    "background task build site",
                    0,
                    1,
                    True,
                )
                self.assertEqual(
                    await ingress.accept(
                        event, VoiceEvidence("alice", True, True, False)
                    ),
                    "unverified",
                )
                gate.wake("wake")
                gate.begin_enrollment()
                gate.enroll("alice", duration=3, clean=True)
                old = TranscriptRevision(
                    "old-session",
                    "turn",
                    2,
                    "background task build site",
                    0,
                    2,
                    True,
                )
                self.assertEqual(
                    await ingress.accept(
                        old, VoiceEvidence("alice", True, True, False)
                    ),
                    "stale",
                )
                self.assertFalse(jobs.list())
                self.assertFalse(controller.history)
            finally:
                await controller.close()

    async def test_answer_to_pending_question_is_not_a_backchannel(self):
        with tempfile.TemporaryDirectory() as directory:

            async def speak(text):
                return True

            async def stop():
                pass

            controller = DuplexController(
                Jobs(Path(directory)),
                Backend(),
                speak,
                stop,
                is_playing=lambda: True,
            )
            try:
                controller.pending_question = True
                self.assertEqual(await controller.accept("yes"), "turn")
            finally:
                await controller.close()
