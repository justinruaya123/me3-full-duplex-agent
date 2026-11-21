"""Portable launcher routing; fixture interpreters, no inference or audio."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def launch(self, mode, environments, *, system, files=None, env=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts" / "me3.sh"
            script.parent.mkdir()
            script.write_text(Path("scripts/me3.sh").read_text())
            for name, value in (files or {}).items():
                (root / name).write_text(value)
            commands = root / "bin"
            commands.mkdir()
            uname = commands / "uname"
            uname.write_text(f'#!/bin/sh\nprintf "%s\\n" "{system}"\n')
            uname.chmod(0o755)
            for name in environments:
                python = root / name / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.write_text(
                    '#!/bin/sh\nprintf "%s\\n" "$0" "$@" "$PROFILE_MARKER"\n'
                )
                python.chmod(0o755)
            return subprocess.run(
                ["bash", str(script), mode],
                capture_output=True, text=True, timeout=5,
                env={"PATH": str(commands) + os.pathsep + os.environ["PATH"], **(env or {})},
            )

    def test_pi_runtime_modes_use_pi_environment(self):
        for mode, module in (("doctor", "me3.doctor"),
                             ("console", "me3.runtime"),
                             ("voice", "me3.runtime")):
            with self.subTest(mode=mode):
                result = self.launch(
                    mode, [".venv-pi", ".venv313"], system="Linux"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(".venv-pi/bin/python", result.stdout)
                self.assertIn(module, result.stdout)
                self.assertEqual("--voice" in result.stdout, mode == "voice")

    def test_mac_runtime_keeps_existing_environment(self):
        result = self.launch(
            "console", [".venv313", ".venv-pi"], system="Darwin"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".venv313/bin/python", result.stdout)

    def test_speech_stays_in_separate_environment(self):
        result = self.launch(
            "speech", [".venv-pi", ".speech-venv312"], system="Linux"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".speech-venv312/bin/python", result.stdout)
        self.assertIn("me3.speech_server", result.stdout)

    def test_speech_loads_only_its_role_file(self):
        files = {".env": "exit 9\n", ".env.speech-server": "PROFILE_MARKER=speech-only\n"}
        result = self.launch("speech", [".speech-venv312"], system="Darwin", files=files)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("speech-only", result.stdout)

    def test_explicit_profile_must_exist_and_has_priority(self):
        env = {"ME3_ENV_FILE": "bench.env"}
        result = self.launch("console", [".venv313"], system="Darwin", env=env)
        self.assertNotEqual(result.returncode, 0)
        result = self.launch("console", [".venv313"], system="Darwin", env=env,
                             files={".env": "exit 9\n", "bench.env": "PROFILE_MARKER=bench\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bench", result.stdout)

    def test_speech_setup_migrates_only_speech_settings_and_preserves_edits(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            shutil.copy('scripts/setup-macos.sh', root / 'scripts')
            shutil.copy('.env.speech.example', root)
            (root / '.env').write_text("ME3_SPEECH_SERVER_TOKEN='private example'\n"
                                       "OPENROUTER_API_KEY=unrelated\n")
            # Fake the speech Python: the test only exercises environment setup.
            python = root / '.speech-venv312/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nexit 0\n')
            python.chmod(0o755)
            env = dict(os.environ, ME3_SPEECH_PYTHON=str(python))
            cmd = ['bash', 'scripts/setup-macos.sh', '--speech-server-only']
            subprocess.run(cmd, cwd=root, env=env, capture_output=True, check=True)
            config = root / '.env.speech-server'
            probe = subprocess.check_output(
                ['bash', '-c', 'source .env.speech-server; printf %s "$ME3_SPEECH_SERVER_TOKEN"'],
                cwd=root, text=True)
            self.assertEqual(probe, 'private example')
            self.assertNotIn('unrelated', config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config.write_text('ME3_SPEECH_SERVER_TOKEN=edited\n')
            subprocess.run(cmd, cwd=root, env=env, capture_output=True, check=True)
            self.assertEqual(config.read_text(), 'ME3_SPEECH_SERVER_TOKEN=edited\n')
