"""Pi-local speech and task MCP servers. PCM stays in bounded host memory."""

import asyncio
import json
from contextlib import AsyncExitStack, aclosing, asynccontextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
import tempfile
import uuid


class CourseMCP:
    def __init__(self, speech, controller, trace):
        self.speech = speech
        self.controller = controller
        self.trace = trace
        self.sessions = {}
        self.clips = {}
        self.output_lock = asyncio.Lock()
        self.output_id = None
        self.producer = None
        self.pcm = None

    async def _cancel(self, stream_id):
        if self.output_id == stream_id and self.producer is not None:
            self.producer.cancel()
            await asyncio.gather(self.producer, return_exceptions=True)
            self.producer = None

    def _servers(self):
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings

        def server(role):
            return FastMCP("me3-" + role, stateless_http=True, json_response=True,
                           transport_security=TransportSecuritySettings(allowed_hosts=["127.0.0.1"]))

        asr, tts, tasks = server("asr"), server("tts"), server("tasks")
        jobs = self.controller.jobs

        @asr.tool()
        async def transcribe(clip_id: str) -> dict:
            """Recognize a bounded host-owned 16 kHz WAV through the configured Whisper server."""
            return {"text": await self.speech.transcribe(self.clips.pop(clip_id))}

        @tts.tool()
        async def speak(text: str, stream_id: str) -> dict:
            """Start local Kokoro and stream PCM to the host's single speaker queue."""
            if stream_id != self.output_id or self.pcm is None or self.producer is not None:
                raise ValueError("No such available playback stream")
            queue = self.pcm

            async def produce():
                try:
                    async with aclosing(self.speech.synthesize(text)) as chunks:
                        async for pcm in chunks:
                            if not pcm or len(pcm) > 4800 or len(pcm) % 2:
                                raise ValueError("Invalid 24 kHz PCM16 chunk")
                            await queue.put(pcm)
                    await queue.put(None)
                except Exception as exc:
                    await queue.put(exc)

            self.producer = asyncio.create_task(produce())
            return {"sample_rate": 24000, "stream_id": stream_id}

        @tts.tool()
        async def tts_cancel(stream_id: str) -> dict:
            """Close exactly this synthesis stream and release native inference."""
            await self._cancel(stream_id)
            return {"closed": True}

        def authorize(epoch=None):
            c = self.controller
            stale = epoch is not None and (c.epoch != epoch or c.user_speaking or c.turn_open)
            if c._closed or stale or not jobs.authorized() or not c.delivery_authorized():
                raise ValueError("Superseded or unauthorized task request")

        @tasks.tool()
        async def submit_job(request: str, request_id: str, epoch: int) -> dict:
            """Submit a committed, owner-scoped task to the durable local worker."""
            authorize(epoch)
            return jobs.submit(request, request_id=request_id)

        @tasks.tool()
        async def get_result(job_id: str, revision: int) -> dict:
            """Return the saved artifact for the selected owner's current revision."""
            authorize()
            return {"text": jobs.result(job_id, expected_revision=revision)}

        @tasks.tool()
        async def get_job(job_id: str) -> dict:
            """Inspect the current owner's job."""
            authorize()
            return jobs.get(job_id)

        @tasks.tool()
        async def cancel_job(job_id: str, revision: int, epoch: int) -> dict:
            """Cancel a job only after a separate committed cancellation request."""
            authorize(epoch)
            return jobs.cancel(job_id, expected_revision=revision)

        @tasks.tool()
        async def revise_job(job_id: str, revision: int, request: str, epoch: int) -> dict:
            """Supersede the named owner job revision."""
            authorize(epoch)
            return jobs.revise(job_id, request, expected_revision=revision)

        @tasks.tool()
        async def preview_job(job_id: str, revision: int, epoch: int) -> dict:
            """Open the verified current revision on loopback."""
            authorize(epoch)
            return {"url": await jobs.preview(job_id, expected_revision=revision)}

        return {"asr": asr, "tts": tts, "tasks": tasks}

    @asynccontextmanager
    async def connect(self):
        import httpx
        import uvicorn
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from starlette.applications import Starlette
        from starlette.routing import Mount

        # The existing aiohttp launcher owns process signals.
        class LocalServer(uvicorn.Server):
            def capture_signals(self):
                return nullcontext()

        async with AsyncExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory(prefix="me3-", dir="/tmp"))
            socket_path = str(Path(folder) / "mcp.sock")
            routes = []
            servers = self._servers()
            for role, service in servers.items():
                routes.append(Mount("/" + role, app=service.streamable_http_app()))
                await stack.enter_async_context(service.session_manager.run())
            host = LocalServer(uvicorn.Config(Starlette(routes=routes), uds=socket_path,
                               lifespan="off", log_config=None, access_log=False, ws="none"))
            runner = asyncio.create_task(host.serve())
            try:
                async with asyncio.timeout(10):
                    while not host.started:
                        if runner.done():
                            await runner
                            raise RuntimeError("Local MCP server did not start")
                        await asyncio.sleep(.01)
                async with AsyncExitStack() as clients:
                    http = await clients.enter_async_context(httpx.AsyncClient(
                        transport=httpx.AsyncHTTPTransport(uds=socket_path), timeout=60))
                    for role in servers:
                        url = "http://127.0.0.1/" + role + "/mcp"
                        rx, tx, _ = await clients.enter_async_context(
                            streamable_http_client(url, http_client=http))
                        session = await clients.enter_async_context(
                            ClientSession(rx, tx, read_timeout_seconds=timedelta(seconds=65)))
                        info = await session.initialize()
                        self.sessions[role] = session
                        self.trace("mcp.ready", server=info.serverInfo.name)
                    yield self
            finally:
                self.sessions.clear()
                await self._cancel(self.output_id)
                host.should_exit = True
                await runner

    async def _call(self, role, name, args):
        result = await self.sessions[role].call_tool(name, args)
        self.trace(name, server=role, ok=not result.isError)
        if result.isError:
            raise RuntimeError(f"Local {role} MCP tool failed: {name}")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        return json.loads(result.content[0].text)

    async def transcribe(self, audio):
        if self.clips or len(audio) > 600000:
            raise ValueError("ASR clip exceeds local capacity")
        key = uuid.uuid4().hex
        self.clips[key] = audio
        try:
            result = await self._call("asr", "transcribe", {"clip_id": key})
            return result["text"]
        finally:
            self.clips.pop(key, None)

    async def synthesize(self, text):
        # Serialize handover while a cancelled generator releases native synthesis.
        async with self.output_lock:
            key = self.output_id = uuid.uuid4().hex
            queue = self.pcm = asyncio.Queue(maxsize=2)
            try:
                await self._call("tts", "speak", {"text": text, "stream_id": key})
                while True:
                    pcm = await asyncio.wait_for(queue.get(), 50)
                    if pcm is None:
                        break
                    if isinstance(pcm, Exception):
                        raise pcm
                    yield pcm
            finally:
                try:
                    await self._call("tts", "tts_cancel", {"stream_id": key})
                finally:
                    await self._cancel(key)
                    self.output_id = self.pcm = None

    async def task(self, name, **arguments):
        return await self._call("tasks", name, arguments)
