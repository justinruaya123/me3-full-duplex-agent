"""Portable launcher routing; fixture interpreters, no inference or audio."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def launch(self, mode, environments):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts" / "me3.sh"
            script.parent.mkdir()
            script.write_text(Path("scripts/me3.sh").read_text())
            for name in environments:
                python = root / name / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.write_text(
                    '#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n'
                )
                python.chmod(0o755)
            return subprocess.run(
                ["bash", str(script), mode],
                capture_output=True, text=True, timeout=5,
                env={"PATH": os.environ["PATH"]},
            )

    def test_pi_runtime_modes_use_pi_environment(self):
        for mode, module in (("doctor", "me3.doctor"),
                             ("console", "me3.runtime"),
                             ("voice", "me3.runtime")):
            with self.subTest(mode=mode):
                result = self.launch(mode, [".venv-pi"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(".venv-pi/bin/python", result.stdout)
                self.assertIn(module, result.stdout)
                self.assertEqual("--voice" in result.stdout, mode == "voice")

    def test_mac_runtime_keeps_existing_environment(self):
        result = self.launch("console", [".venv313"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".venv313/bin/python", result.stdout)

    def test_speech_stays_in_separate_environment(self):
        result = self.launch("speech", [".venv-pi", ".speech-venv312"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".speech-venv312/bin/python", result.stdout)
        self.assertIn("me3.speech_server", result.stdout)
