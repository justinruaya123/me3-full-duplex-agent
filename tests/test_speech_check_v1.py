"""A speech check cannot turn failed or hung native work into readiness."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


class BoundedCheckTests(unittest.TestCase):
    expected = {"asr_model": "selected-asr", "tts_model": "selected-tts"}

    def test_nonzero_exit_or_malformed_report_cannot_claim_success(self):
        from me3.speech_check import run_bounded_check

        for source in (
            'print(\'{"passed":true}\'); raise SystemExit(7)',
            'print("not a readiness report")',
        ):
            with self.subTest(source=source):
                result = run_bounded_check(
                    [sys.executable, "-c", source], self.expected, timeout=5
                )
                self.assertFalse(result["passed"])

    def test_timeout_reaps_worker_even_after_it_printed_success(self):
        from me3.speech_check import run_bounded_check

        result = run_bounded_check(
            [sys.executable, "-u", "-c",
             'import time; print(\'{"passed":true}\'); time.sleep(60)'],
            self.expected,
            timeout=0.2,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_type"], "TimeoutError")
        with self.assertRaises(ProcessLookupError):
            os.kill(result["worker_pid"], 0)

    def test_success_requires_the_exact_selected_models(self):
        from me3.speech_check import run_bounded_check

        for model, passed in (("substitute", False), ("selected-tts", True)):
            with self.subTest(model=model):
                payload = json.dumps({
                    "passed": True,
                    "asr_model": "selected-asr",
                    "tts_model": model,
                })
                result = run_bounded_check(
                    [sys.executable, "-c", "print(" + repr(payload) + ")"],
                    self.expected,
                    timeout=5,
                )
                self.assertEqual(result["passed"], passed)

    def test_timeout_cleans_descendants_that_keep_stdout_open(self):
        from me3.speech_check import run_bounded_check

        source = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c',"
            "'import time; time.sleep(1.2)']); time.sleep(5)"
        )
        started = time.monotonic()
        result = run_bounded_check(
            [sys.executable, "-c", source], self.expected, timeout=0.1
        )
        self.assertFalse(result["passed"])
        self.assertLess(time.monotonic() - started, 0.8)

    def test_oversized_output_is_stopped_before_the_time_deadline(self):
        from me3.speech_check import run_bounded_check

        result = run_bounded_check(
            [sys.executable, "-u", "-c",
             "import time; print('x'*70000,flush=True); time.sleep(5)"],
            self.expected,
            timeout=0.5,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_type"], "OutputLimitError")


class ServiceProcessTests(unittest.TestCase):
    def test_startup_timeout_terminates_a_blocked_native_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "native.pid"
            native = (
                "import asyncio,os,time; from pathlib import Path; "
                "from me3.speech_server import "
                "MLXSpeechModels,SpeechServerConfig; "
                f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "models=MLXSpeechModels(SpeechServerConfig('a','t','v','s')); "
                "asyncio.run(models._native('tts',time.sleep,60))"
            )
            parent = (
                "import sys; "
                "from me3.speech_check import run_guarded_service; "
                "raise SystemExit(run_guarded_service("
                f"[sys.executable,'-c',{native!r}],startup_timeout=.3))"
            )
            result = subprocess.run(
                [sys.executable, "-c", parent],
                capture_output=True, timeout=3,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(pid_file.is_file())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    def test_service_shutdown_terminates_inflight_native_work(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "native.pid"
            native = (
                "import os,time; from pathlib import Path; "
                f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                "fd=int(os.environ['ME3_SPEECH_READY_FD']); "
                "os.write(fd,b'READY\\n'); os.close(fd); time.sleep(60)"
            )
            parent = (
                "import sys; "
                "from me3.speech_check import run_guarded_service; "
                "raise SystemExit(run_guarded_service("
                f"[sys.executable,'-c',{native!r}],startup_timeout=2))"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", parent],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 2
                while not pid_file.exists() and process.poll() is None:
                    if time.monotonic() > deadline:
                        self.fail("Native service did not start")
                    time.sleep(.01)
                self.assertTrue(pid_file.is_file())
                process.terminate()
                self.assertEqual(process.wait(timeout=2), 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
