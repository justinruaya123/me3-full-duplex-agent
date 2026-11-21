import unittest


class VoiceBenchmarkTests(unittest.TestCase):
    def test_only_microphone_user_messages_open_a_spoken_turn(self):
        from integrations.pi_routing_benchmark import microphone_transcript
        def message(role, text):
            return {"type": "message_start", "message": {
                "role": role, "content": [{"type": "text", "text": text}]}}
        self.assertEqual(microphone_transcript(message("user", "Microphone transcript: seven plus five")), "seven plus five")
        self.assertIsNone(microphone_transcript(message("user", "seven plus five")))
        self.assertIsNone(microphone_transcript(message("assistant", "Microphone transcript: fake")))

    def test_course_launches_the_current_bmo_voice_and_model(self):
        import os
        import sys
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from integrations import fdbench_pi_launcher

        with tempfile.TemporaryDirectory() as run:
            args = ["launcher", "--project", str(Path.cwd()), "--log-dir", run,
                    "--url", "ws://127.0.0.1:18391"]
            with patch.object(sys, "argv", args), patch.dict(os.environ, ME3_FDBENCH_THINKING="off"), \
                    patch.dict(sys.modules, fdbench_marks=SimpleNamespace(mark=lambda *a: None)), \
                    patch("subprocess.Popen", side_effect=InterruptedError) as launch:
                with self.assertRaises(InterruptedError):
                    fdbench_pi_launcher.main()
            command = launch.call_args.args[0]
            env = launch.call_args.kwargs["env"]
            self.assertEqual(command[command.index("--model") + 1], "deepseek/deepseek-v4.1-flash")
            self.assertEqual(env["ME3_FOREGROUND_MODEL"], command[command.index("--model") + 1])
            self.assertEqual(env["ME3_VOICE_TTS"], "bmo")
            self.assertEqual(env["ME3_LIVE_BENCHMARK"], "1")
            self.assertEqual(env["ME3_MEMORY_ENABLED"], "0")

    def test_routing_requires_the_same_job_revision_after_conversation(self):
        from integrations.pi_routing_benchmark import assess

        job = dict(name="delegate_task", id="job1", revision=1, status="queued")
        receipt = dict(name="delegated_task_status", id="job1", revision=2, status="completed")
        turns = [{"tools": [job]}, {"tools": [], "text": "12"}, {"tools": [receipt]}]
        self.assertEqual(assess(turns), dict(delegated_once=True, direct_answer=True, same_job=False))
        receipt["revision"] = 1
        self.assertTrue(assess(turns)["same_job"])

    def test_waiting_cue_is_excluded_from_answer_audio(self):
        from benchmark import stage_answer_audio
        from pathlib import Path
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "sessions" / "session-000001"
            session.mkdir(parents=True)
            t = "2026-11-21T00:00:00+00:00"
            events = [dict(event="trial_start", group="stage_latency", trial="test", t=t),
                      dict(event="trial_end", trial="test", t=t)]
            (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
            events = [dict(event="answer", id="turn", at=t),
                      dict(event="first_output", id="other", vadEndToOutputMs=20, at=t),
                      dict(event="wait_cue_output", id="turn", at=t)]
            log = session / "events.jsonl"
            log.write_text("".join(json.dumps(e) + "\n" for e in events))
            self.assertEqual(stage_answer_audio(root, root / "sessions")["with_answer_audio"], 0)
            with log.open("a") as stream:
                print(json.dumps(dict(event="first_output", id="turn", at=t, vadEndToOutputMs=1500)), file=stream)
            result = stage_answer_audio(root, root / "sessions")
            self.assertEqual(result["with_answer_audio"], 1)
            self.assertEqual(result["p95_seconds"], 1.5)

    def test_never_accept_a_remote_audio_recorder(self):
        from integrations.fdbench_pi import loopback_audio_url
        for url in ("ws://example.com:8791", "wss://127.0.0.1@example.org", "file:///tmp/pcm"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                loopback_audio_url(url)
        self.assertEqual(loopback_audio_url("ws://127.0.0.1:8791"),
                         "ws://127.0.0.1:8791?out_sr=24000")

    def test_suppressed_and_missed_cues_remain_in_denominators(self):
        from benchmark import summarize
        rows = [{"expected": True, "observed": False},
                {"expected": False, "observed": False}]
        self.assertEqual(summarize(rows), {"opportunities": 1, "hits": 0,
                                           "quiet_windows": 1, "false_alarms": 0})

    def test_digital_output_distinguishes_cues_and_resumable_speech(self):
        from integrations.fdbench_pi import DigitalDevice
        d = DigitalDevice()
        d.playing.extend(b"\x41\x01" * 32)
        d.paused = True
        d.listening_cue.extend(b"\x22\x01" * 5)
        self.assertEqual(d.render(8), b"\x22\x01" * 5)
        self.assertIsNone(d.first_reply_signal)
        self.assertEqual(len(d.playing), 64)
        d.paused = False
        self.assertEqual(len(d.render(8)), 16)
        self.assertIsNotNone(d.first_reply_signal)
        d.clear()
        self.assertEqual(d.render(8), b"")

    def test_cue_matching_checks_the_pause_window_and_rejects_other_audio(self):
        import numpy as np
        from integrations.listening_benchmark import cue_peak
        ref = np.random.default_rng(21).normal(size=4000)
        played = np.zeros(48000)
        played[20000:24000] = ref * .2
        self.assertIsNone(cue_peak(played, ref, 0, 1))
        self.assertAlmostEqual(cue_peak(played, ref, 1, 2), 1.25)
        self.assertIsNone(cue_peak(played, ref, 1.5, 2.5))

    def test_darwin_group_denial_is_ignored_only_after_verified_exit(self):
        from integrations.benchmark_control import OwnedLauncher
        from types import SimpleNamespace
        from unittest.mock import patch
        child = OwnedLauncher.__new__(OwnedLauncher)
        child.process = SimpleNamespace(pid=222, poll=lambda: 0)
        with patch("sys.platform", "darwin"), patch("os.killpg", side_effect=PermissionError), \
                patch("subprocess.check_output", return_value="  222 Z\n  123 S\n"):
            self.assertFalse(child._signal_group(0))
        with patch("sys.platform", "darwin"), patch("os.killpg", side_effect=PermissionError), \
                patch("subprocess.check_output", return_value="  222 S\n"):
            with self.assertRaises(PermissionError):
                child._signal_group(0)

    def test_failed_timing_stub_is_not_counted_as_recorded_audio(self):
        import json
        import tempfile
        from pathlib import Path
        from benchmark import recording_counts
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            for name in ("ok", "lost"):
                trial = run / "trials" / name
                trial.mkdir(parents=True)
                (trial / "timing.json").write_text(json.dumps({"group": "stage_latency"}))
            for filename in ("her.flac", "played.flac"):
                (run / "trials/ok" / filename).touch()
            counts = recording_counts(run)
            self.assertEqual(counts["recording_count"], 1)
            self.assertEqual(counts["phrase_trials_recorded"], 1)
            self.assertEqual(counts["phrase_recordings_with_agent_audio"], 0)
