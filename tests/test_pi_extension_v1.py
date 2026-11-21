import json
from pathlib import Path
import unittest


class PiPackageTests(unittest.TestCase):
    def test_local_pi_package_declares_the_terminal_extension(self):
        package = json.loads(Path("package.json").read_text())
        entries = package["pi"]["extensions"]
        self.assertEqual(entries, ["./me3/pi_extension.mjs"])
        self.assertTrue(Path(entries[0]).is_file())

    def test_operator_launcher_defaults_to_the_pi_extension(self):
        import os
        import subprocess
        import tempfile
        env_file = tempfile.NamedTemporaryFile()
        self.addCleanup(env_file.close)
        run = subprocess.run(
            ["bash", "scripts/me3.sh", "agent", "--version"],
            env={**os.environ, "ME3_ENV_FILE": env_file.name, "ME3_PI_BIN": "/bin/echo",
                 "ME3_FOREGROUND_PROFILE": "pi-fast", "ME3_FOREGROUND_PROVIDER": "catalog",
                 "ME3_FOREGROUND_MODEL": "voice"}, capture_output=True, text=True,
        )
        self.assertIn("pi_extension.mjs", run.stdout)
        self.assertIn("--tools me3_route,me3_files,me3_github,me3_prototype ", run.stdout)
        self.assertIn("me3/skills/github/SKILL.md", run.stdout)
        self.assertIn("--thinking off", run.stdout)
