import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "integrations" / "voicechat"


def install_fixture_bootstrap(plugin):
    shutil.copy(PLUGIN / "project.mjs", plugin)
    scope = plugin / "node_modules/@earendil-works"
    scope.mkdir()
    (scope / "pi-coding-agent").symlink_to(
        PLUGIN / "node_modules/@earendil-works/pi-coding-agent", target_is_directory=True)
    search = plugin / "node_modules/@arcanemachine/pi-web-search/index.ts"
    search.parent.mkdir(parents=True)
    search.touch()


class ConversationPromptTests(unittest.TestCase):
    def test_launcher_prepares_editable_files_without_overwriting_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin = Path(folder) / "integrations/voicechat"
            pi = plugin / "node_modules/.bin/pi"
            pi.parent.mkdir(parents=True)
            install_fixture_bootstrap(plugin)
            (plugin / "start.sh").write_bytes((PLUGIN / "start.sh").read_bytes())
            shutil.copytree(PLUGIN / "templates", plugin / "templates")
            pi.write_text('#!/bin/sh\nprintf "%s\\0" "$PI_CODING_AGENT_DIR"\nprintf "%s\\0" "$@"\n')
            pi.chmod(0o700)
            profile = Path(folder) / "voice prompts"
            env = dict(os.environ, VOICECHAT_PYTHON=sys.executable, ME3_CLIENT_HOME=folder, ME3_VOICE_TTS="kokoro", ME3_PI_BIN="/missing/system/pi",
                       PI_CODING_AGENT_DIR="/wrong/system/profile",
                       ME3_VOICE_PROMPT_DIR=str(profile),
                       ME3_FOREGROUND_PROVIDER="test", ME3_FOREGROUND_MODEL="test")
            command = ["bash", str(plugin / "start.sh")]
            subprocess.run(command, env=env, capture_output=True, check=True)
            self.assertEqual(sorted(p.name for p in profile.iterdir()),
                             ["SOUL.md", "SYSTEM.md", "USER.md", "WORKER.md"])
            for section in profile.iterdir():
                self.assertTrue(section.read_text().startswith("<!-- ME3 editing guide"))
                self.assertEqual(section.stat().st_mode & 0o777, 0o600)
            user = profile / "USER.md"
            self.assertEqual(user.stat().st_mode & 0o777, 0o600)
            user.write_text("sample private preference")
            result = subprocess.run(command, env=env, capture_output=True, check=True)
            self.assertEqual(user.read_text(), "sample private preference")
        args = result.stdout.decode().split("\0")
        self.assertEqual(args[args.index("--thinking") + 1], "low")
        self.assertIn("web_lookup", args[args.index("--tools") + 1].split(","))
        self.assertNotIn("sample private preference", result.stdout.decode())
        self.assertEqual(args[0], str(Path(folder).resolve() / ".local/pi"))
        self.assertEqual(Path(args[args.index("--extension") + 1]).resolve(), plugin.resolve() / "pi.mjs")
        self.assertEqual(args[args.index("--tools") + 1], "read_trial_brief,create_website,delegate_task,delegated_task_status,subagent,revise_delegated_task,web_lookup,recall_web_search,portfolio_research,show_dashboard,update_dashboard,remember_detail,publish_github_pages")

    def test_live_human_launcher_shares_owner_profile_and_honors_memory_opt_out(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plugin = root / "integrations/voicechat"
            pi = plugin / "node_modules/.bin/pi"
            pi.parent.mkdir(parents=True)
            install_fixture_bootstrap(plugin)
            shutil.copy(PLUGIN / "start.sh", plugin)
            shutil.copytree(PLUGIN / "templates", plugin / "templates")
            pi.write_text('#!/bin/sh\nprintf "%s\\n" "$ME3_VOICE_PROMPT_DIR" "$ME3_MEMORY_ENABLED"\n')
            pi.chmod(0o700)
            (root / "en_US-lessac-medium.onnx").touch()
            env = dict(os.environ, VOICECHAT_PYTHON=sys.executable, ME3_CLIENT_HOME=folder, ME3_PIPER_DIR=folder, ME3_VOICE_TTS="lessac",
                       DEEPGRAM_API_KEY="fixture", OPENROUTER_API_KEY="fixture")
            env.pop("ME3_VOICE_PROMPT_DIR", None)
            env.pop("ME3_MEMORY_ENABLED", None)
            for enabled in ("1", "0"):
                if enabled == "0":
                    env["ME3_MEMORY_ENABLED"] = enabled
                result = subprocess.run(["bash", str(plugin / "start.sh"), "--live-benchmark"],
                                        env=env, capture_output=True, text=True, check=True)
                profile, memory = result.stdout.splitlines()
                self.assertEqual(Path(profile).resolve(), root.resolve() / ".local/voice-prompts")
                self.assertEqual(memory, enabled)
