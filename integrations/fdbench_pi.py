"""Loopback-only replacement for the Pi plugin's microphone and speaker."""
import asyncio
import threading
import time
from urllib.parse import urlsplit

from me3.parakeet import FRAME
from me3.pi_audio_device import Devices, render_output


def loopback_audio_url(url):
    address = urlsplit(url)
    if (address.scheme != "ws" or address.hostname != "127.0.0.1"
            or address.username is not None or address.password is not None
            or not address.port or address.path not in ("", "/")
            or address.query or address.fragment):
        raise ValueError("fdbench requires ws://127.0.0.1:PORT")
    return f"ws://127.0.0.1:{address.port}?out_sr=24000"


class DigitalDevice:
    enqueue = Devices.enqueue

    def __init__(self):
        self.playing = bytearray()
        self.listening_cue = bytearray()
        self.listener_signal_frames = 0
        self.first_listener_signal = None
        self.wait_clip = None
        self.lock = threading.Lock()
        self.paused = False
        self.flush = False
        self.first_reply_signal = None
        self.last_audible = self.capture_time = 0.
        self.signal_frames = self.delivered = 0
        self.input = asyncio.Queue(maxsize=100)

    def clear(self):
        self.wait_clip = None
        self.playing.clear()
        self.listening_cue.clear()
        self.flush = True

    def close(self):
        self.clear()

    def render(self, count):
        return render_output(self, count, time.monotonic())

    async def receive(self, ws):
        import aiohttp
        pending = bytearray()
        was_paused = False
        async for message in ws:
            if message.type != aiohttp.WSMsgType.BINARY:
                raise RuntimeError("Unexpected fdbench audio message")
            pcm = message.data
            if not pcm or len(pcm) % 2:
                raise ValueError("Expected complete PCM16 samples")
            now = time.monotonic()
            if self.flush or (self.paused and not was_paused):
                await ws.send_json({"event": "clear"})
                self.flush = False
            was_paused = self.paused
            # Clock the virtual 24 kHz speaker from the 16 kHz direct rig.
            out = self.render(len(pcm) * 3 // 4)
            if out:
                await ws.send_bytes(out)
            pending.extend(pcm)
            while len(pending) >= FRAME:
                if self.input.full():
                    raise BufferError("Digital capture overrun: two seconds of pending audio")
                self.input.put_nowait((now, bytes(pending[:FRAME])))
                del pending[:FRAME]
        if ws.exception():
            raise RuntimeError("fdbench audio link failed") from ws.exception()

    async def frames(self):
        while True:
            self.capture_time, pcm = await self.input.get()
            yield pcm
