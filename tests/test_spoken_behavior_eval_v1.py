import unittest

from integrations.spoken_behavior_eval import backchannel_evidence


class SpokenBehaviorEvidenceTests(unittest.TestCase):
    def test_requires_old_pcm_after_resolution_and_audio_overlap_at_onset(self):
        origin = 10**9
        rows = [
            {
                "event": "pcm",
                "mono_ns": origin,
                "context": "old",
                "peak": 300,
                "samples": 480,
            },
            {
                "event": "pcm",
                "mono_ns": origin + 1000,
                "context": "old",
                "peak": 300,
                "samples": 480,
            },
            {"event": "user_started", "mono_ns": origin + 2000},
            {"event": "provisional_backchannel_resumed", "mono_ns": origin + 5000},
            {
                "event": "pcm",
                "mono_ns": origin + 10000,
                "context": "new",
                "peak": 300,
                "samples": 480,
            },
        ]
        onset = origin + 500
        self.assertFalse(backchannel_evidence(rows, onset, "old")["passed"])
        rows[-1]["context"] = "old"
        self.assertTrue(backchannel_evidence(rows, onset, "old")["passed"])
        rows[-1]["peak"] = 0
        self.assertFalse(backchannel_evidence(rows, onset, "old")["passed"])
        self.assertFalse(
            backchannel_evidence(rows, origin + 10**8, "old")["overlapped"]
        )

    def test_reply_context_requires_new_foreground_dispatch_and_submission(self):
        from integrations.spoken_behavior_eval import reply_context

        rows = [
            {"event": "speech_submitted", "utterance": "other"},
            {"event": "foreground_request", "text": "Tell me about rain."},
        ]
        self.assertIsNone(reply_context(rows))
        rows.append({"event": "speech_submitted", "utterance": "reply"})
        self.assertEqual(reply_context(rows), "reply")

    def test_positive_control_changes_only_the_acknowledgment_stimulus(self):
        from integrations.spoken_behavior_eval import stimuli_for

        original = stimuli_for("mm-hmm")
        alternate = stimuli_for("yeah")
        self.assertEqual(original["acknowledge"], "Mm-hmm.")
        self.assertEqual(alternate["acknowledge"], "Yeah.")
        self.assertEqual(original | {"acknowledge": "Yeah."}, alternate)
        self.assertEqual(stimuli_for("mm-hmm"), original)

    def test_disfluency_rejects_a_worker_launched_before_final_or_for_old_topic(self):
        from integrations.spoken_behavior_eval import disfluency_evidence

        text = "Write a poem about summer, no, winter instead."
        rows = [
            {"event": "asr_partial", "mono_ns": 1, "text": "Write about summer."},
            {"event": "asr_final", "mono_ns": 2, "text": "Background task, " + text},
            {"event": "delegated", "mono_ns": 3, "job_id": "abc"},
            {"event": "worker_request", "mono_ns": 4, "text": text},
        ]
        self.assertTrue(disfluency_evidence(rows)["passed"])
        rows[-1]["mono_ns"] = 1
        self.assertFalse(disfluency_evidence(rows)["passed"])
        rows[-1].update(mono_ns=4, text="Write about summer")
        self.assertFalse(disfluency_evidence(rows)["passed"])
