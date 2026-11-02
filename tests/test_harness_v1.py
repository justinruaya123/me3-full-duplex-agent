"""Subprocess tests use fixtures, not installed agent harnesses."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from me3.harnesses import JsonProcessBackend, PiBackend, hermes_backend


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    def fixture(self, source):
        path = self.root / "child.py"
        path.write_text(source, encoding="utf-8")
        return (sys.executable, str(path))

    async def test_json_process_returns_valid_result(self):
        command = self.fixture(
            'import json,sys\n'
            'request=json.load(sys.stdin)\n'
            'print(json.dumps({"text": request["prompt"] + " done"}))\n'
        )
        result = await JsonProcessBackend(command).run("draft", self.root)
        self.assertEqual(result, "draft done")

    async def test_provider_error_is_not_a_mock_result(self):
        command = self.fixture('raise RuntimeError("provider down")\n')
        with self.assertRaises(RuntimeError):
            await JsonProcessBackend(command).run("draft", self.root)

    async def test_malformed_or_empty_result_fails(self):
        for source in ('print("not json")', 'print(\'{"text": ""}\')'):
            with self.assertRaises((ValueError, RuntimeError)):
                await JsonProcessBackend(self.fixture(source)).run(
                    "draft", self.root,
                )

    async def test_output_is_bounded(self):
        command = self.fixture('print("x" * 20000)')
        with self.assertRaises((ValueError, RuntimeError)):
            await JsonProcessBackend(command, max_bytes=4096).run(
                "draft", self.root,
            )

    async def test_timeout_reaps_child(self):
        command = self.fixture('import time\ntime.sleep(10)\n')
        with self.assertRaises(TimeoutError):
            await JsonProcessBackend(command, timeout=0.05).run(
                "draft", self.root,
            )

    async def test_cancellation_reaps_local_child(self):
        marker = self.root / "pid"
        command = self.fixture(
            'import os,time,pathlib\n'
            f'pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n'
            'time.sleep(10)\n'
        )
        task = asyncio.create_task(JsonProcessBackend(command).run(
            "draft", self.root,
        ))
        for _ in range(100):
            if marker.exists():
                break
            await asyncio.sleep(0.01)
        self.assertTrue(marker.exists())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        import os
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)

    async def test_pi_waits_for_settled_not_agent_end(self):
        command = self.fixture(
            'import json,sys\n'
            'r=json.loads(sys.stdin.readline())\n'
            'print(json.dumps({"type":"response","id":r["id"],'
            '"success":True,"data":{"disposition":"started"}}),flush=True)\n'
            'print(json.dumps({"type":"agent_end"}),flush=True)\n'
            'print(json.dumps({"type":"agent_settled"}),flush=True)\n'
            'q=json.loads(sys.stdin.readline())\n'
            'assert q["type"] == "get_last_assistant_text"\n'
            'print(json.dumps({"type":"response","id":q["id"],'
            '"success":True,"data":{"text":"final\\u2028answer"}}),'
            'flush=True)\n'
            'sys.stdin.read()\n'
        )
        result = await PiBackend(command).run("draft", self.root)
        self.assertEqual(result, "final\u2028answer")

    async def test_pi_command_failure_surfaces(self):
        command = self.fixture(
            'import json,sys\n'
            'r=json.loads(sys.stdin.readline())\n'
            'print(json.dumps({"type":"response","id":r["id"],'
            '"success":False,"error":"denied"}),flush=True)\n'
        )
        with self.assertRaises(RuntimeError):
            await PiBackend(command).run("draft", self.root)

    async def test_pi_aborted_message_does_not_publish_partial_text(self):
        command = self.fixture(
            'import json,sys\n'
            'sys.stdin.readline()\n'
            'print(json.dumps({"type":"message_end","message":'
            '{"role":"assistant","stopReason":"aborted"}}),flush=True)\n'
        )
        with self.assertRaises(RuntimeError):
            await PiBackend(command).run("draft", self.root)

    def test_hermes_requires_explicit_source_and_configuration(self):
        with self.assertRaises(ValueError):
            hermes_backend({})
