"""Experimental Pi stdio audio device. Only finalized mic text enters Pi."""

import asyncio
import base64
import json
import os
import queue
import re
import sys
import time
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from me3.pi_audio_device import Devices, FRAMES, RATE, emit

ORIGIN = ""  # Configure ME3_VOICECHAT_ORIGIN for the optional speech relay.


class DecoderCapacityError(RuntimeError):
    """The inference host needs a fresh voice context."""


def voice_chunk_limit(seconds):
    if type(seconds) is int and seconds > 0:
        return max(1, seconds * RATE // FRAMES - 1)
    return None


def decoder_capacity_error(error):
    return (isinstance(error, dict) and error.get("code") == "inference_error"
            and re.search(r"\bllama_decode\b.*\bfailed with code 1\s*$",
                          str(error.get("message", ""))) is not None)


class VoiceEvents:
    def __init__(self):
        self.seen = OrderedDict()

    def accept(self, event):
        kind = event.get("type")
        if kind == "input_audio_buffer.speech_started":
            item = event.get("item_id")
            return {"kind": "onset", "id": item if isinstance(item, str) and len(item) <= 256 else None}
        if kind == "conversation.item.input_audio_transcription.completed":
            key, text = event.get("item_id"), event.get("transcript")
            tag = "final"
        elif kind == "app.tool_call" and event.get("ok") is True and event.get("name") == "delegate_task":
            key, text = event.get("call_id"), event.get("prompt")
            tag = "proposal"
        else:
            return None
        if not isinstance(key, str) or not 0 < len(key) <= 256:
            return None
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
            return None
        if (tag, key) in self.seen:
            return None
        if len(self.seen) >= 2048:
            raise ValueError("Voice session limit reached. Reconnect.")
        self.seen[tag, key] = True
        return {"kind": tag, "id": key, "text": text.strip()}


class RelayResults:
    def __init__(self, session, max_bytes):
        self.session = session
        self.max_bytes = max_bytes
        self.pending = {}

    def open(self, call, *, now):
        self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
        key, item = call.get("call_id"), call.get("input_item_id")
        ttl = call.get("result_timeout_ms")
        if (call.get("session_id") != self.session or key in self.pending
                or not all(isinstance(i, str) and 0 < len(i) <= 256 for i in (key, item))
                or type(ttl) is not int or ttl <= 0 or len(self.pending) >= 8):
            return False
        self.pending[key] = (item, now + ttl / 1000)
        return True

    def take(self, command, *, now):
        key = command.get("id")
        pending = self.pending.get(key)
        summary = command.get("summary")
        if (not pending or pending[0] != command.get("item") or now >= pending[1]
                or command.get("status") not in ("success", "decline", "failure", "timeout")
                or not isinstance(summary, str) or not 0 < len(summary.encode()) <= self.max_bytes):
            return None
        del self.pending[key]
        return dict(type="app.tool_result", session_id=self.session, call_id=key,
                    input_item_id=pending[0], status=command["status"], summary=summary)


class NativeReplyGate:
    """Keep a rejected orphan tool call from speaking over the next quiet gap."""

    def __init__(self):
        self.muted = False

    def observe(self, kind, code=None):
        if kind == "input_audio_buffer.speech_started":
            self.muted = False
        elif kind == "app.error" and code == "tool_input_unresolved":
            first = not self.muted
            self.muted = True
            return first
        return not (self.muted and kind.startswith("response.output_audio"))


async def run(*, fixture=None, voice="nemotron"):
    import aiohttp

    events = VoiceEvents()
    origin = os.environ.get("ME3_VOICECHAT_ORIGIN", ORIGIN).rstrip("/")
    endpoint = urlsplit(origin)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.path or endpoint.query or endpoint.fragment:
        raise ValueError("ME3_VOICECHAT_ORIGIN must be an HTTPS origin without credentials")
    tts = None
    if voice == "kokoro":
        from me3.local_tts import LocalKokoro, DEFAULT_DIR
        tts = LocalKokoro(Path(os.environ.get("ME3_KOKORO_DIR", DEFAULT_DIR)))
    device = speaking = None
    epoch = 0
    sent = received = 0
    tasks = []

    async def cut():
        nonlocal speaking
        if device:
            device.clear()
        if speaking:
            speaking.cancel()
            await asyncio.gather(speaking, return_exceptions=True)
            speaking = None

    async def speak(text, revision):
        try:
            before = device.delivered
            async for pcm in tts.synthesize(text):
                if revision != epoch:
                    return
                await device.enqueue(pcm)
            while device.playing and revision == epoch:
                await asyncio.sleep(.02)
            if revision == epoch:
                emit("played", frames=(device.delivered - before) // 2)
        except asyncio.CancelledError:
            if device.delivered > before:
                emit("interrupted", frames=(device.delivered - before) // 2)
            raise
        except Exception as exc:
            emit("error", message=str(exc))

    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(origin.replace("https:", "wss:") + "/ws",
                                     origin=origin, heartbeat=15, max_msg_size=1 << 20) as ws:
            ready = asyncio.Event()
            results = None
            gate = NativeReplyGate()
            max_chunks = None

            async def listen():
                nonlocal epoch, received, device, results, max_chunks
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        raise ConnectionError("Voice relay disconnected")
                    e = msg.json()
                    kind = e.get("type")
                    if not gate.observe(kind, e.get("code")):
                        continue
                    if kind == "session.created":
                        update = {"type": "session.update"}
                        if voice == "nemotron":
                            update["app"] = {"version": 1, "tool_mode": "client-executed"}
                        await ws.send_json(update)
                    elif kind == "session.updated" and not ready.is_set():
                        max_chunks = voice_chunk_limit(e.get("app", {}).get("max_audio_seconds"))
                        if voice == "nemotron":
                            app = e.get("app", {})
                            if (app.get("version") != 1 or app.get("tool_mode") != "client-executed"
                                    or not isinstance(app.get("session_id"), str)
                                    or type(app.get("max_summary_bytes")) is not int):
                                raise RuntimeError("Relay did not negotiate client-executed v1")
                            results = RelayResults(app["session_id"], min(512, app["max_summary_bytes"]))
                        if fixture is None:
                            device = Devices()
                        ready.set()
                        emit("ready", fixture=fixture is not None, voice=voice)
                    elif kind in {"app.error", "error"}:
                        error = e.get("error") or e.get("message")
                        if kind == "app.error" and str(e.get("code", "")).startswith("tool_"):
                            if gate.muted and device and voice == "nemotron":
                                device.clear()
                            emit("receipt", state=e["code"], id=e.get("call_id"))
                            continue
                        if decoder_capacity_error(error):
                            raise DecoderCapacityError("Nemotron decoder context reached capacity")
                        raise RuntimeError(str(error)[:320])
                    elif kind == "app.tool_result.accepted" and results and e.get("session_id") == results.session:
                        results.pending.pop(e.get("call_id"), None)
                        emit("receipt", state=e.get("status"), source=e.get("source"),
                             id=e.get("call_id"), audio_chunks=received)
                    elif kind == "response.output_audio.delta":
                        received += 1
                        if voice == "nemotron" and device:
                            device.native_audio(e["delta"])
                    elif voice == "nemotron" and kind in {
                        "response.output_audio_transcript.delta",
                        "response.output_audio_transcript.done",
                    }:
                        done = kind.endswith(".done")
                        text = e.get("transcript" if done else "delta")
                        if isinstance(text, str):
                            emit("assistant_done" if done else "assistant_delta", text=text[:4000])
                    elif kind == "conversation.item.input_audio_transcription.delta":
                        delta = e.get("delta")
                        if isinstance(delta, str) and delta:
                            emit("partial", text=delta[:1000])
                    elif event := events.accept(e):
                        if event["kind"] == "proposal" and results:
                            if not results.open(e, now=time.monotonic()):
                                continue
                            event["item"] = e["input_item_id"]
                        if event["kind"] == "onset":
                            epoch += 1
                            await cut()
                        emit(**event, epoch=epoch)
                raise ConnectionError("Voice relay closed")

            async def upload():
                nonlocal sent
                async with asyncio.timeout(15):
                    await ready.wait()
                buf = bytearray()
                if fixture:
                    import wave
                    with wave.open(str(fixture)) as f:
                        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, RATE) or f.getnframes() > RATE * 30:
                            raise ValueError("Fixture must be mono PCM16 24 kHz, at most 30s")
                        data = f.readframes(f.getnframes())
                    buf.extend(data)
                    silence_until = time.monotonic() + len(data) / (RATE * 2) + 45
                while True:
                    if fixture:
                        if not buf:
                            if time.monotonic() >= silence_until:
                                return
                            buf.extend(bytes(2 * FRAMES))
                    else:
                        if device.overrun:
                            raise BufferError("Microphone fell behind; reconnect")
                        try:
                            buf.extend(device.capture())
                        except queue.Empty:
                            await asyncio.sleep(.005)
                            continue
                    while len(buf) >= 2 * FRAMES or (fixture and buf):
                        if max_chunks is not None and sent >= max_chunks:
                            raise DecoderCapacityError("Reached the relay audio session limit")
                        chunk = bytes(buf[:2 * FRAMES]).ljust(2 * FRAMES, b"\0")
                        del buf[:2 * FRAMES]
                        await ws.send_json({"type": "input_audio_buffer.append",
                                            "audio": base64.b64encode(chunk).decode("ascii")})
                        sent += 1
                        if device and sent % 4 == 0:
                            samples = memoryview(chunk).cast("h")
                            emit("level", peak=max(max(samples), -min(samples)),
                                 speaker_frames=device.signal_frames)
                        if fixture:
                            await asyncio.sleep(.08)

            async def commands():
                nonlocal speaking
                reader = asyncio.StreamReader()
                pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
                try:
                    while line := await reader.readline():
                        c = json.loads(line)
                        if c.get("op") == "close":
                            return
                        if results and c.get("op") == "tool_result":
                            payload = results.take(c, now=time.monotonic())
                            if payload:
                                await ws.send_json(payload)
                            else:
                                emit("receipt", state="local result outside pending call", id=c.get("id"))
                        if (tts and c.get("op") == "say" and device and c.get("epoch") == epoch
                                and isinstance(c.get("text"), str) and 0 < len(c["text"]) <= 4000):
                            await cut()
                            speaking = asyncio.create_task(speak(c["text"], epoch))
                finally:
                    pipe.close()

            try:
                tasks = [asyncio.create_task(fn()) for fn in (listen, upload, commands)]
                finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await cut()
                if device:
                    device.close()
                if tts:
                    await tts.close()
                if not ws.closed:
                    with suppress(ConnectionError):
                        await ws.send_json({"type": "session.close"})
                emit("closed", sent_chunks=sent, remote_audio_chunks=received)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--voice", choices=("nemotron", "kokoro"), default="nemotron")
    args = parser.parse_args()
    try:
        asyncio.run(run(fixture=args.fixture, voice=args.voice))
    except DecoderCapacityError as exc:
        emit("error", message=str(exc))
        sys.exit(os.EX_TEMPFAIL)
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(1)
