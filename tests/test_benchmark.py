import json
import tempfile
import unittest
from pathlib import Path

from me3.benchmark import benchmark, percentile


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_is_explicitly_non_acoustic_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-run"
            await benchmark(output, 2)
            report = json.loads((output / "metrics.json").read_text())
            self.assertFalse(report["hardware_qualified"])
            self.assertEqual(report["backend"], "mock")
            self.assertEqual(report["tracks"]["workers_1"]["successes"], 2)
            self.assertTrue((output / "trials.jsonl").is_file())
            with self.assertRaises(FileExistsError):
                await benchmark(output, 2)

    async def test_invalid_trials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                await benchmark(Path(directory) / "run", 0)

    def test_nearest_rank_percentile(self):
        self.assertEqual(percentile(list(range(1, 21)), 0.95), 19)
        self.assertIsNone(percentile([], 0.95))
