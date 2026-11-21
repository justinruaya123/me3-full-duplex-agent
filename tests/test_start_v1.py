"""Bootstrap key handling against a private, disposable client config."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import setup


class StartTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / ".env"
        self.template = Path(temp.name) / "example"
        self.template.write_bytes(b'OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"\n')

    def test_blank_preserves_entire_existing_file(self):
        original = b"# operator config\r\nexport OPENROUTER_API_KEY='existing'\r\n"
        self.path.write_bytes(original)
        before = self.path.stat().st_ino
        setup.save_keys(self.path, self.template, {"OPENROUTER_API_KEY": ""})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_ino, before)

    def test_entered_secret_survives_shell_sourcing_and_skipped_key_survives(self):
        self.path.write_text("# custom\nexport OPENROUTER_API_KEY='old'\nBRAVE_SEARCH_API_KEY=keep\n")
        token = "a'$HOME `false` \"b#c"
        setup.save_keys(self.path, self.template, {
            "OPENROUTER_API_KEY": token, "BRAVE_SEARCH_API_KEY": "",
        })
        loaded = subprocess.check_output(
            ["bash", "-c", 'source "$1"; printf "%s\\n%s" "$OPENROUTER_API_KEY" "$BRAVE_SEARCH_API_KEY"',
             "test", str(self.path)], text=True)
        self.assertEqual(loaded, token + "\nkeep")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_fresh_skipped_keys_keep_environment_fallback(self):
        setup.save_keys(self.path, self.template, {})
        self.assertEqual(self.path.read_bytes(), self.template.read_bytes())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        value = subprocess.check_output(
            ["bash", "-c", 'source "$1"; printf %s "$OPENROUTER_API_KEY"', "test", str(self.path)],
            env={**os.environ, "OPENROUTER_API_KEY": "inherited"})
        self.assertEqual(value, b"inherited")

    def test_wizard_keeps_skipped_keys_on_both_hosts(self):
        from unittest.mock import patch

        root = self.path.parent
        (root / ".env.example").write_text("ME3_ASR_API_KEY=\n")
        (root / ".env.speech.example").write_text("ME3_SPEECH_SERVER_TOKEN=\n")
        server = root / ".env.speech-server"
        server.write_bytes(b"ME3_SPEECH_SERVER_TOKEN=server-token\n")
        self.path.write_bytes(b"ME3_ASR_API_KEY=client-token\n")
        with patch.object(setup, "ROOT", root):
            setup.configure(self.path, True, lambda label: "")
            self.assertEqual(server.read_bytes(), b"ME3_SPEECH_SERVER_TOKEN=server-token\n")
            self.assertEqual(self.path.read_bytes(), b"ME3_ASR_API_KEY=client-token\n")
            setup.configure(self.path, True, lambda label: "shared" if label.startswith("Shared") else "")
        self.assertIn("ME3_ASR_API_KEY=shared", self.path.read_text())
        self.assertIn("ME3_TTS_API_KEY=shared", self.path.read_text())
        self.assertEqual(server.read_text(), "ME3_SPEECH_SERVER_TOKEN=shared\n")

    def test_standalone_key_setup_creates_persistent_config_without_installing(self):
        result = subprocess.run(
            [os.sys.executable, "scripts/setup.py", "--no-prompt"],
            env={**os.environ, "ME3_ENV_FILE": str(self.path)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), (setup.ROOT / ".env.example").read_bytes())
        self.path.write_text("BRAVE_SEARCH_API_KEY=existing\n")
        subprocess.run([os.sys.executable, "scripts/setup.py", "--no-prompt"],
                       env={**os.environ, "ME3_ENV_FILE": str(self.path)}, check=True,
                       capture_output=True)
        self.assertEqual(self.path.read_text(), "BRAVE_SEARCH_API_KEY=existing\n")
