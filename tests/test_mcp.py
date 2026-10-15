"""Real SDK smoke test, skipped explicitly when the optional SDK is absent."""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("mcp"),
    "Optional MCP SDK is not installed",
)
class MCPSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_submit_and_result(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as state:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "me3", "mcp", "--state", state],
                env=dict(os.environ),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    discovered = await session.list_tools()
                    names = {tool.name for tool in discovered.tools}
                    self.assertIn("submit_job", names)
                    self.assertIn("stop_speaking", names)
                    result = await session.call_tool(
                        "submit_job",
                        {"request": "report"},
                    )
                    job = json.loads(result.content[0].text)
                    for _ in range(100):
                        result = await session.call_tool(
                            "get_job",
                            {"job_id": job["id"]},
                        )
                        current = json.loads(result.content[0].text)
                        if current["status"] == "completed":
                            break
                        await asyncio.sleep(0.02)
                    self.assertEqual(current["status"], "completed")
                    result = await session.call_tool(
                        "get_result",
                        {"job_id": job["id"]},
                    )
                    self.assertFalse(result.isError)
