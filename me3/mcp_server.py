"""
Local stdio MCP services. Optional SDK; no TCP listener or invented protocol.
"""

from __future__ import annotations

import asyncio
import base64
import uuid


def control_server(supervisor, controller):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("me3-control")

    @server.tool()
    async def submit_job(request: str) -> dict:
        """
        Start bounded background work and return a durable job identifier.
        """
        return supervisor.submit(request)

    @server.tool()
    async def get_job(job_id: str) -> dict:
        """Read the authoritative state of one job."""
        return supervisor.get(job_id)

    @server.tool()
    async def list_jobs() -> dict:
        """List local jobs; status is independent of conversation focus."""
        return {"jobs": supervisor.list()}

    @server.tool()
    async def cancel_job(job_id: str) -> dict:
        """
        Explicitly cancel a specific local job; not a speech interruption.
        """
        supervisor.cancel(job_id)
        await supervisor.wait(job_id)
        return supervisor.get(job_id)

    @server.tool()
    async def revise_job(job_id: str, request: str) -> dict:
        """Supersede a running job revision, rejecting late results."""
        return supervisor.update(job_id, request)

    @server.tool()
    async def get_result(job_id: str) -> dict:
        """Read a completed result; does not change conversational focus."""
        text = supervisor.result(job_id)
        return {"text": text[:16000], "truncated": len(text) > 16000}

    @server.tool()
    async def set_focus(job_id: str = "") -> dict:
        """
        Explicitly switch to a job, or clear focus with an empty identifier.
        """
        controller.set_focus(job_id or None)
        return {"focus": controller.focus}

    @server.tool()
    async def ask(request: str) -> dict:
        """Run one foreground answer while independent jobs continue."""
        return {"text": await controller.ask(request)}

    @server.tool()
    async def stop_speaking() -> dict:
        """Cancel only foreground response work. Background jobs continue."""
        controller.interrupt()
        return {"background_jobs_cancelled": False}

    return server


def speech_server(speech):
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("me3-speech")
    streams: dict = {}

    @server.tool()
    async def transcribe(wav_base64: str) -> dict:
        """
        Transcribe a <=16-second mono PCM16/16 kHz WAV through an inference
        API.
        """
        if len(wav_base64) > 800000:
            raise ValueError("Encoded audio exceeds the upload limit.")
        audio = base64.b64decode(wav_base64, validate=True)
        return {"text": await speech.transcribe(audio)}

    @server.tool()
    async def tts_open(text: str) -> dict:
        """
        Open a single 24 kHz PCM16 synthesis stream; only inference is remote.
        """
        if streams:
            raise RuntimeError("Close the existing speech stream first.")
        if not text.strip() or len(text) > 16000:
            raise ValueError("Invalid synthesis text.")
        stream_id = uuid.uuid4().hex
        streams[stream_id] = (speech.synthesize(
            text,
        ).__aiter__(), asyncio.Lock())
        return {
            "stream_id": stream_id, "sample_rate": 24000,
            "format": "pcm_s16le",
        }

    @server.tool()
    async def tts_next(stream_id: str) -> dict:
        """
        Return up to 100 ms of PCM, or eof. Prototype pull-based streaming.
        """
        iterator, lock = streams[stream_id]
        async with lock:
            try:
                chunk = await asyncio.wait_for(anext(iterator), 50)
            except StopAsyncIteration:
                streams.pop(stream_id, None)
                return {"audio_base64": "", "eof": True}
            except BaseException:
                streams.pop(stream_id, None)
                await iterator.aclose()
                raise
        return {"audio_base64": base64.b64encode(chunk).decode(), "eof": False}

    @server.tool()
    async def tts_cancel(stream_id: str) -> dict:
        """
        Close synthesis. Playback flushing remains the Pi audio service's job.
        """
        entry = streams.pop(stream_id, None)
        if entry:
            iterator, lock = entry
            async with lock:
                await iterator.aclose()
        return {"closed": True}

    return server


class MCPSpeech:
    """
    Runtime speech client: the Pi-hosted MCP server owns ASR/TTS API calls.
    """

    def __init__(self, session) -> None:
        self.session = session

    async def _call(self, name: str, arguments: dict) -> dict:
        import json

        result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"Speech MCP operation failed: {name}")
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        return json.loads(result.content[0].text)

    async def transcribe(self, audio: bytes) -> str:
        result = await self._call("transcribe", {
            "wav_base64": base64.b64encode(audio).decode(),
        })
        return result["text"]

    async def synthesize(self, text: str):
        stream = await self._call("tts_open", {"text": text})
        stream_id = stream["stream_id"]
        try:
            while True:
                result = await self._call("tts_next", {"stream_id": stream_id})
                if result["eof"]:
                    return
                yield base64.b64decode(result["audio_base64"], validate=True)
        finally:
            try:
                await asyncio.wait_for(
                    self._call("tts_cancel", {"stream_id": stream_id}), 2
                )
            except (TimeoutError, RuntimeError):
                pass
