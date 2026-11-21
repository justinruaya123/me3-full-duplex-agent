"""One Deepgram Nova-3 stream per locally controlled utterance."""

import asyncio
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

    async def connect(self):
        import aiohttp

        try:
            async with asyncio.timeout(10):
                self.ws = await self.client.ws_connect(
                    self.url, headers={"Authorization": "Token " + self.token},
                    params={"model": "nova-3", "language": "en-US", "encoding": "linear16",
                            "sample_rate": "16000", "channels": "1", "interim_results": "true",
                            "punctuate": "true", "endpointing": "600"},
                    max_msg_size=262144, heartbeat=15)
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status in (401, 403):
                raise PermissionError(f"Deepgram rejected the key (HTTP {exc.status})") from None
            raise RuntimeError(f"Deepgram handshake failed (HTTP {exc.status})") from None
        self.reader = asyncio.create_task(self.receive(self.ws))

    async def receive(self, ws):
        import aiohttp

        result = Results()
        try:
            async for msg in ws:
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
        if self.fault.done():
            raise self.fault.result()
        if not self.ws or self.ws.closed or self.reader.done():
            if self.reader:
                await self.reader
            await self.connect()
        self.current = Utterance(self.notify)
        self.current.finalized_frames = 0
        self.current.settled_text = ""
        self.current.endpoint_frames = 0
        return self.current

    async def flush_words(self):
        # Settle the current words without closing the socket or ending the turn.
        await self.ws.send_json({"type": "Finalize"})

    async def finish(self, *, cancel=False):
        turn = self.current
        if not turn:
            raise RuntimeError("No open Deepgram utterance")
        if cancel:
            await self.close()
            self.reader = None
            self.current = None
            return None
        turn.expect = "final"
        turn.end_sent = time.monotonic()
        await self.ws.send_json({"type": "CloseStream"})
        await asyncio.wait([turn.done, self.fault], timeout=7, return_when=asyncio.FIRST_COMPLETED)
        if self.fault.done():
            raise self.fault.result()
        if not turn.done.done():
            raise TransientASRError("Deepgram finalization timed out")
        await self.reader
        self.current = None
        return turn.done.result()
