"""Authenticated, single-utterance Parakeet WebSocket client."""

import asyncio
import os
import time
import uuid
from pathlib import Path

URL = ""  # Loopback transport fixture override.
MODEL = "nvidia/parakeet-unified-en-0.6b"
FRAME = 640


class TransientASRError(ConnectionError):
    """Start a fresh session and abandon any unfinished input."""


def credential():
    token = os.environ.get("ME3_ASR_TOKEN", "").strip()
    if not token:
        path = Path(__file__).resolve().parents[1] / ".local/parakeet.token"
        if path.is_file() and path.stat().st_mode & 0o077 == 0:
            token = path.read_text().strip()
    if not token or any(ch.isspace() for ch in token):
        raise ValueError("Configure ME3_ASR_TOKEN or a mode-600 .local/parakeet.token")
    return token


class Utterance:
    def __init__(self, notify):
        self.id = uuid.uuid4().hex
        self.notify = notify
        self.revision = -1
        self.text = ""
        self.expect = None
        self.done = asyncio.get_running_loop().create_future()
        self.first_frame = self.first_partial = self.end_sent = None
        self.frames = 0
        self.next_frame = 0.

    def accept(self, event):
        if event.get("id") != self.id or self.done.done():
            return
        kind = event.get("type")
        if kind == "canceled" and self.expect == kind:
            self.done.set_result(None)
            return
        if kind not in ("partial", "final"):
            raise ValueError("Unexpected ASR utterance event")
        if self.expect == "canceled" and kind == "partial":
            return
        rev, text = event.get("revision"), event.get("text")
        if type(rev) is not int or rev < 0 or not isinstance(text, str) or len(text) > 16000:
            raise ValueError("Invalid ASR hypothesis")
        if kind == "final" and (self.expect != "final" or rev < self.revision):
            raise ValueError("Unsolicited or stale ASR final")
        if kind == "partial" and rev <= self.revision:
            return
        self.revision = rev
        self.text = text
        now = time.monotonic()
        metrics = {}
        if kind == "partial" and text.strip() and self.first_partial is None:
            self.first_partial = now
            if self.first_frame is not None:
                metrics["first_partial_ms"] = round(1000 * (now - self.first_frame), 1)
        if kind == "final":
            if self.end_sent is not None:
                metrics["end_to_final_ms"] = round(1000 * (now - self.end_sent), 1)
            self.done.set_result(text.strip())
        self.notify(kind, id=self.id, revision=rev, text=text, **metrics)


class Stream:
    pace_audio = True

    def __init__(self, client, notify, token):
        self.client, self.notify, self.token = client, notify, token
        self.ws = self.reader = self.current = None
        self.fault = asyncio.get_running_loop().create_future()

    async def connect(self):
        url = URL or os.environ.get("ME3_PARAKEET_URL", "")
        if not URL and not url.startswith("wss://"):
            raise ValueError("Set ME3_PARAKEET_URL to the authenticated wss:// endpoint")
        import aiohttp

        try:
            async with asyncio.timeout(12):
                self.ws = await self.client.ws_connect(
                    url, headers={"Authorization": "Bearer " + self.token},
                    max_msg_size=65536, heartbeat=15, ssl=True)
                ready = await self.ws.receive_json()
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status in (401, 403):
                raise PermissionError(f"Parakeet authentication rejected (HTTP {exc.status})") from None
            if exc.status == 429 or exc.status >= 500:
                raise TransientASRError(f"Parakeet unavailable (HTTP {exc.status})") from None
            raise ValueError(f"Parakeet handshake failed (HTTP {exc.status})") from None
        if ready.get("type") == "error":
            self.server_error(ready)
        if (ready.get("type"), ready.get("version"), ready.get("model"),
                ready.get("sample_rate")) != ("ready", 1, MODEL, 16000):
            raise ValueError("Invalid Parakeet ready event")
        self.reader = asyncio.create_task(self.receive(self.ws))

    @staticmethod
    def server_error(event):
        code = str(event.get("code", "unknown"))[:64]
        if code in ("audio_overflow", "overloaded", "server_busy", "idle_timeout",
                    "queue_full", "service_unavailable", "worker_unavailable", "busy"):
            raise TransientASRError(f"ASR {code}; repeat any interrupted utterance")
        raise ValueError("ASR rejected operation: " + code)

    async def receive(self, ws):
        import aiohttp
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    raise TransientASRError("ASR WebSocket transport failed")
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise ValueError("Unexpected ASR response format")
                event = msg.json()
                if event.get("type") == "error":
                    if event.get("code") == "idle_timeout" and self.current is None:
                        break
                    self.server_error(event)
                if self.current is not None:
                    self.current.accept(event)
            if self.current is not None:
                raise TransientASRError("ASR disconnected during speech")
            self.notify("standby")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.fault.done():
                self.fault.set_result(exc)
        finally:
            await ws.close()

    async def begin(self):
        if self.current is not None:
            raise RuntimeError("Previous ASR utterance has not settled")
        if self.fault.done():
            raise self.fault.result()
        if self.reader is None or self.reader.done() or self.ws.closed:
            if self.reader:
                await self.reader
            await self.connect()
        self.current = Utterance(self.notify)
        await self.ws.send_json({"type": "start", "id": self.current.id})
        return self.current

    async def audio(self, pcm):
        turn = self.current
        if turn is None or turn.expect or len(pcm) != FRAME or turn.frames >= 6000:
            raise ValueError("Invalid Parakeet frame or utterance length")
        if self.pace_audio:
            await asyncio.sleep(max(0., turn.next_frame - time.monotonic()))
            turn.next_frame = max(time.monotonic() - .002, turn.next_frame) + .020
        now = time.monotonic()
        if turn.first_frame is None:
            turn.first_frame = now
        await self.ws.send_bytes(pcm)
        turn.frames += 1

    async def finish(self, *, cancel=False):
        turn = self.current
        if turn is None or turn.expect:
            raise RuntimeError("No open ASR utterance")
        turn.expect = "canceled" if cancel else "final"
        turn.end_sent = time.monotonic()
        await self.ws.send_json({"type": "cancel" if cancel else "end", "id": turn.id})
        await asyncio.wait([turn.done, self.fault], timeout=7, return_when=asyncio.FIRST_COMPLETED)
        if self.fault.done():
            raise self.fault.result()
        if not turn.done.done():
            raise TransientASRError("ASR final/cancel acknowledgment timed out")
        self.current = None
        return turn.done.result()

    async def close(self):
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.ws:
            await self.ws.close()
        if self.current and not self.current.done.done():
            self.current.done.cancel()
