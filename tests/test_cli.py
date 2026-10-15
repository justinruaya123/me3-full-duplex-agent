import asyncio
import sys
import tempfile
import unittest

from me3.backends import make_backend
from me3.onit_runner import build_config


class CLITests(unittest.IsolatedAsyncioTestCase):
    async def test_quit_does_not_start_or_finish_queued_foreground(self):
        with tempfile.TemporaryDirectory() as directory:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "me3", "chat", "--state", directory,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(b"hello\n/quit\n"), 3,
            )
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertNotIn("ASSISTANT:", stdout.decode())

    def test_onit_config_is_tool_disabled_and_uses_local_workspace(self):
        config = build_config({
            "foreground": True, "workspace": "/tmp/local-work",
            "settings": {"host": "http://inference/v1", "model": "test"},
        })
        self.assertFalse(config["serving"]["harness_tools"])
        self.assertFalse(config["serving"]["code_execution"])
        self.assertTrue(
            all(not s["enabled"] for s in config["mcp"]["servers"])
        )
        self.assertEqual(config["data_path"], "/tmp/local-work")
        self.assertTrue(config["loop"])

    def test_missing_real_backend_configuration_is_not_mocked(self):
        with self.assertRaises(ValueError):
            make_backend({"backend": "onit"})
