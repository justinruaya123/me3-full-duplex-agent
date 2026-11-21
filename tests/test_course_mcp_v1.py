import asyncio
import importlib.util
import unittest
from unittest.mock import AsyncMock, Mock

from me3.course_mcp import CourseMCP


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK is not installed")
class CourseMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_three_local_servers_and_closes_cancelled_synthesis(self):
        closed = asyncio.Event()

        async def synthesize(text):
            try:
                yield b"\x01\x00" * 480
                await asyncio.Event().wait()
            finally:
                closed.set()

        voice = Mock(transcribe=AsyncMock(return_value="recognized"), synthesize=synthesize)
        controller = Mock(epoch=3, _closed=False, user_speaking=False, turn_open=False)
        controller.jobs.submit.return_value = {"id":"job1", "revision":1}
        calls = []
        course = CourseMCP(voice, controller, lambda name, **fields: calls.append(name))
        async with course.connect():
            self.assertEqual(await course.transcribe(b"bounded captured wav"), "recognized")
            job = await course.task("submit_job", request="Write a brief", request_id="turn-4", epoch=3)
            self.assertEqual(job["id"], "job1")
            controller.jobs.submit.assert_called_once_with("Write a brief", request_id="turn-4")
            stream = course.synthesize("Speak")
            self.assertEqual(len(await anext(stream)), 960)
            await stream.aclose()
            self.assertTrue(closed.is_set())
            controller.epoch += 1
            with self.assertRaises(RuntimeError):
                await course.task("submit_job", request="Stale", request_id="turn-4", epoch=3)
        self.assertIn("transcribe", calls)
        self.assertIn("tts_cancel", calls)
