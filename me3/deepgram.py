"""One Deepgram Nova-3 stream per locally controlled utterance."""

import asyncio
import os
import time

from me3.parakeet import Stream, TransientASRError, Utterance


class Results:
    def __init__(self):
        self.final = ""

    def update(self, event):
        text = event["channel"]["alternatives"][0]["transcript"].strip()
        combined = " ".join(part for part in (self.final, text) if part)
        if len(combined) > 16000:
            raise ValueError("Deepgram transcript exceeds the turn limit")
        if event["is_final"]:
            self.final = combined
        return combined


class DeepgramStream(Stream):
    # The capture device already clocks live PCM. Drain queued preroll immediately.
    pace_audio = False
    url = "wss://api.deepgram.com/v1/listen"

    def __init__(self, client, notify, token):
        super().__init__(client, notify, token)
        self.warming = None
        self.released = None

    async def open_socket(self):
        import aiohttp

        try:
            async with asyncio.timeout(10):
                return await self.client.ws_connect(
                    self.url, headers={"Authorization": "Token " + self.token},
                    params={"model": "nova-3", "language": "en-US", "encoding": "linear16",
                            "sample_rate": "16000", "channels": "1", "interim_results": "true",
                            "punctuate": "true", "endpointing": "250", "redact_usage": "true",
                            "keyterm": os.environ.get("ME3_WAKE_PHRASE", "").strip() or "Beemo"},
                    max_msg_size=262144, heartbeat=15, timeout=aiohttp.ClientWSTimeout(ws_close=.5))
        except TimeoutError:
            raise TransientASRError("Deepgram connection timed out") from None
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status in (401, 403):
                raise PermissionError(f"Deepgram rejected the key (HTTP {exc.status})") from None
            raise RuntimeError(f"Deepgram handshake failed (HTTP {exc.status})") from None

    async def connect(self):
        self.ws = await self.open_socket()
        self.reader = asyncio.create_task(self.receive(self.ws))

    async def receive(self, ws):
        import aiohttp

        result = Results()
        try:
            while not ws.closed:
                try:
                    msg = await ws.receive(timeout=4)
                except TimeoutError:
                    if self.current is None:
                        await ws.send_json({"type": "KeepAlive"})
                    continue
                if msg.type != aiohttp.WSMsgType.TEXT:
                    raise TransientASRError("Deepgram transport failed")
                event = msg.json()
                turn = self.current
                if event.get("type") == "Results" and turn is not None:
                    text = result.update(event)
                    # A provider segment final settles words. The local controller
                    # still owns the end of the conversational turn.
                    segment = event["channel"]["alternatives"][0]["transcript"].strip()
                    if event["is_final"] and segment and "start" in event and "duration" in event:
                        turn.finalized_frames = round((event["start"] + event["duration"]) / .020)
                        turn.settled_text = result.final
                        if event.get("speech_final") and not event.get("from_finalize"):
                            turn.endpoint_frames = turn.finalized_frames
                    turn.accept(dict(type="partial", id=turn.id, revision=turn.revision+1, text=text))
                elif event.get("type") == "Metadata" and turn and turn.expect == "final":
                    turn.accept(dict(type="final", id=turn.id, revision=turn.revision+1, text=result.final))
                    break
                elif event.get("type") == "Error":
                    raise TransientASRError("Deepgram stream error")
            if self.current and not self.current.done.done():
                raise TransientASRError("Deepgram disconnected before finalization")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.current and not self.fault.done():
                self.fault.set_result(exc)
        finally:
            await ws.close()

    async def begin(self):
        if self.current:
            raise RuntimeError("Previous Deepgram utterance is still open")
        if self.warming is not None:
            try:
                await self.warming
            finally:
                self.warming = None
        if self.fault.done():
            raise self.fault.result()
        if not self.ws or self.ws.closed or self.reader.done():
            if self.reader:
                await asyncio.gather(self.reader, return_exceptions=True)
            await self.connect()
        self.current = Utterance(self.notify)
        self.current.finalized_frames = 0
        self.current.settled_text = ""
        self.current.endpoint_frames = 0
        self.released = asyncio.Event()
        self.prepare_next(self.released)
        return self.current

    async def flush_words(self):
        # Settle the current words without closing the socket or ending the turn.
        await self.ws.send_json({"type": "Finalize"})

    def finish_endpoint(self):
        """The local floor controller accepted the matching provider-final segment."""
        if self.fault.done():
            raise self.fault.result()
        turn = self.current
        if (not turn or not turn.endpoint_frames or turn.endpoint_frames != turn.finalized_frames
                or turn.text != turn.settled_text):
            raise RuntimeError("Utterance has no matching ASR endpoint")
        turn.expect = "final"
        turn.accept(dict(type="final", id=turn.id, revision=turn.revision + 1, text=turn.text))
        self.current = None
        self.reader.cancel()
        self.released.set()
        return turn.done.result()

    def prepare_next(self, released):
        previous = self.reader
        previous_socket = self.ws

        async def replace():
            ws = None
            try:
                ws = await self.open_socket()
                # Only the active socket receives microphone frames. An open
                # standby uses control messages during a long utterance.
                while not released.is_set():
                    try:
                        await asyncio.wait_for(released.wait(), timeout=4)
                    except TimeoutError:
                        await ws.send_json({"type": "KeepAlive"})
                if previous is not None:
                    await asyncio.gather(previous, return_exceptions=True)
                if not previous_socket.closed:
                    await previous_socket.close()
                self.ws = ws
                self.reader = asyncio.create_task(self.receive(ws))
                ws = None
            finally:
                if ws is not None:
                    await ws.close()

        self.warming = asyncio.create_task(replace())

    async def close(self):
        if self.warming is not None:
            self.warming.cancel()
            await asyncio.gather(self.warming, return_exceptions=True)
            self.warming = None
        await super().close()

    async def finish(self, *, cancel=False):
        turn = self.current
        if not turn:
            raise RuntimeError("No open Deepgram utterance")
        if cancel:
            turn.done.cancel()
            self.current = None
            self.reader.cancel()
            self.released.set()
            return None
        turn.expect = "final"
        turn.end_sent = time.monotonic()
        await self.ws.send_json({"type": "CloseStream"})
        await asyncio.wait([turn.done, self.fault], timeout=7, return_when=asyncio.FIRST_COMPLETED)
        if self.fault.done():
            raise self.fault.result()
        if not turn.done.done():
            raise TransientASRError("Deepgram finalization timed out")
        self.current = None
        self.released.set()
        return turn.done.result()
