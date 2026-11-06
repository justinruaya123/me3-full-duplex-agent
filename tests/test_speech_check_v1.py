"""A speech check cannot turn failed or hung native work into readiness."""

import json
import os
import sys
import unittest


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
