"""Pi.dev stdio device for local turn control, Parakeet ASR and Kokoro playback."""

import argparse
import asyncio
import json
import os
import queue
import re
import sys
import time
import wave
from collections import deque
from pathlib import Path

from me3 import bmo
from me3.capture import SmartTurn
from me3.incremental import is_acknowledgment, is_listening_receipt
from me3.local_tts import DEFAULT_DIR, LocalBmo, LocalKokoro, LocalPiper
from me3.parakeet import FRAME, Stream, TransientASRError, credential
from me3.pi_audio_device import Devices, emit


async def frames(device, fixture):
    import numpy as np
    import soxr

    if fixture:
        with wave.open(str(fixture)) as f:
            rate = f.getframerate()
            if (f.getnchannels(), f.getsampwidth()) != (1, 2) or f.getnframes() > rate * 110:
                raise ValueError("Use a mono PCM16 speech fixture of at most 110 seconds")
            pcm = soxr.resample(np.frombuffer(f.readframes(f.getnframes()), dtype="<i2"),
                                rate, 16000).astype("<i2").tobytes()
        pcm = bytes(FRAME * 12) + pcm + bytes(FRAME * 175)
        due = time.monotonic()
        for offset in range(0, len(pcm), FRAME):
            await asyncio.sleep(max(0., due - time.monotonic()))
            due += .02
            yield pcm[offset:offset + FRAME].ljust(FRAME, b"\0")
        return

    # PortAudio negotiates 24 kHz mono for the full-duplex callback and the AEC
    # render reference. Preserve resampler history across callback boundaries.
    converter = soxr.ResampleStream(24000, 16000, 1, dtype="int16", quality="LQ")
    buf = bytearray()
    while True:
        if device.overrun:
            raise TransientASRError("Microphone overrun; interrupted utterance discarded")
        try:
            near = device.capture()
        except queue.Empty:
            await asyncio.sleep(.003)
            continue
        buf.extend(converter.resample_chunk(np.frombuffer(near, dtype="<i2")).tobytes())
        while len(buf) >= FRAME:
            yield bytes(buf[:FRAME])
            del buf[:FRAME]


class NearEndSpeech:
    """For an overlapping turn, require local speech after the speaker pauses."""

    def start(self, now, last_output):
        self.clear = now - last_output > .40
        self.after = now + .22
        self.frames = 0

    def observe(self, capture_time, speaking):
        if not self.clear and capture_time >= self.after:
            self.frames = self.frames + 1 if speaking else 0
            self.clear = self.frames >= 3


# The ASR hypothesis can buy a little listening time; only the final can dispatch.
HESITATION = re.compile(r"(?:a+h+|u+h+|u+m+|e+rm+)[.,!…]*", re.I)
OPEN_END = re.compile(
    r"\b(?:and|or|but|because|that|the|a|an|to|my|our|your|if|we|they|i|is|was)\W*$",
    re.I,
)
DICTATION = re.compile(
    r"[@/=`?]|\d{3,}|\b(?:spell\w*|dictat\w*|verbatim|number|code|password|approve|confirm"
    r"|quot(?:e|ed|ing)|(?:the|my|your) name is|word for word|take (?:this|it) down|exactly as)\b", re.I,
)


def unfinished_clause(text):
    return len(text.split()) > 1 and not text.endswith("?") and OPEN_END.search(text)


class ListeningCue:
    def __init__(self):
        self.last_id = None
        self.last_time = float("-inf")

    def eligible(self, item, text, frames, *, now):
        return (item != self.last_id and now - self.last_time >= 12 and frames >= 100
                and len(text.split()) >= 5 and not DICTATION.search(text))

    def offer(self, item, text, frames, *, now):
        if not self.eligible(item, text, frames, now=now):
            return False
        self.last_id, self.last_time = item, now
        return True


def trim_cue_lead(pcm):
    """Keep 20 ms of attack before the first audible sample in a 24 kHz cached clip."""
    for index, sample in enumerate(memoryview(pcm).cast("h")):
        if abs(sample) >= 250:
            return pcm[2 * max(0, index - 480):]
    return pcm


class Playback:
    def __init__(self, device):
        self.device = device
        profile = os.environ.get("ME3_VOICE_TTS") or (
            "lessac" if os.environ.get("ME3_LIVE_BENCHMARK") == "1" else "kokoro")
        self.clips = {}
        self.listen_index = 0
        self.listener_receipt = None
        if profile == "bmo":
            root = Path(os.environ.get("ME3_BMO_DIR", bmo.ROOT))
            self.engine = LocalBmo(root)
            if device:
                catalog = bmo.phrases()
                self.listen_phrases = catalog["listening"]
                for group in catalog.values():
                    for text in group:
                        pcm = bmo.read_clip(root / "clips", text)
                        self.clips[text] = trim_cue_lead(pcm) if text in self.listen_phrases else pcm
        elif profile == "lessac":
            self.engine = LocalPiper(Path(os.environ["ME3_PIPER_DIR"]))
        elif profile == "kokoro":
            self.engine = LocalKokoro(Path(os.environ.get("ME3_KOKORO_DIR", DEFAULT_DIR)))
        else:
            raise ValueError(f"Unknown voice profile {profile!r}")
        self.task = None
        self.idle_output = False
        self.epoch = 0
        self.held = False
        self.output_baseline = None
        self.allow_cue = False
        self.awaiting_answer = False
        self.last_reply_end = float("-inf")
        self.cues = ListeningCue()
        if device and not self.clips:
            path = Path(__file__).resolve().parents[1] / "integrations/voicechat/listening.wav"
            with wave.open(str(path)) as wav:
                self.cue_pcm = wav.readframes(wav.getnframes())

    def observe_listener(self):
        if not self.listener_receipt:
            return
        item, text, before = self.listener_receipt
        with self.device.lock:
            complete = not self.device.listening_cue and self.device.signal_frames > before
        if complete:
            self.listener_receipt = None
            emit("listener_played", id=item, text=text)

    def quiet_cue(self):
        if self.device:
            self.observe_listener()
            self.listener_receipt = None
            with self.device.lock:
                self.device.listening_cue.clear()

    def acknowledge(self, u, trigger="turn_incomplete", pause_frames=0):
        if (self.device and self.allow_cue and self.held and not (self.task and not self.task.done())
                and self.cues.offer(u.id, u.text, u.frames, now=time.monotonic())):
            if self.clips:
                text = self.listen_phrases[self.listen_index]
                self.listen_index = (self.listen_index + 1) % len(self.listen_phrases)
                pcm = self.clips[text]
            else:
                text, pcm = None, self.cue_pcm
            with self.device.lock:
                if text:
                    self.listener_receipt = (u.id, text, self.device.signal_frames)
                self.device.listening_cue[:] = pcm
            emit("listening_cue", id=u.id, text=text, trigger=trigger, detected_gap_ms=pause_frames * 20)

    def observe_output(self):
        self.observe_listener()
        if (self.device and self.output_baseline is not None
                and self.device.first_reply_signal is not None):
            self.output_baseline = None
            emit("playing", receipt=self.receipt, first_output=self.device.first_reply_signal,
                 tts_start=self.tts_start)

    def hold(self, value):
        self.quiet_cue()
        self.held = value
        if self.device:
            with self.device.lock:
                self.device.paused = value
            if value and self.task and not self.task.done():
                emit("paused")

    async def cut(self):
        self.quiet_cue()
        self.epoch += 1
        if self.device:
            self.device.clear()
        if self.task:
            interrupted = not self.task.done()
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
            if interrupted:
                emit("interrupted")
        self.output_baseline = None
        self.hold(False)

    async def audio(self, text, cached):
        if cached:
            pcm = self.clips[text]
            for offset in range(0, len(pcm), 4800):
                yield pcm[offset:offset + 4800]
        else:
            async for chunk in self.engine.synthesize(text):
                yield chunk

    async def speak(self, text, question=None, receipt=None, cached=False):
        try:
            self.tts_start = time.monotonic()
            self.receipt = receipt or question
            with self.device.lock:
                self.device.first_reply_signal = None
            before = self.device.delivered
            signal_before = self.device.signal_frames
            self.output_baseline = signal_before
            if os.environ.get("ME3_FDBENCH_URL"):
                from fdbench_marks import mark
                mark("tts_request", t=self.tts_start)
            first = True
            async for chunk in self.audio(text, cached):
                if first and os.environ.get("ME3_FDBENCH_URL"):
                    first = False
                    mark("tts_first_audio")
                await self.device.enqueue(chunk)
            while self.device.playing:
                await asyncio.sleep(.02)
            self.observe_output()
            if self.device.signal_frames > signal_before:
                self.last_reply_end = time.monotonic()
            emit("played", frames=(self.device.delivered - before) // 2,
                 signal_frames=self.device.signal_frames - signal_before,
                 question=question, receipt=receipt)
        except Exception as exc:
            emit("error", message=f"Speech playback failed: {exc}")
        finally:
            self.output_baseline = None


async def local_turns(stream, source, vad, smart, playback, *, after_gap=False):
    from pipecat.audio.vad.vad_analyzer import VADState

    preroll = deque(maxlen=12)
    # SmartTurn v3 evaluates the recent audio window. Keep a bounded tail.
    evidence = deque(maxlen=400)
    decision = probe = None
    probed_item = probe_gap = None
    complete = None
    near = NearEndSpeech()
    pause_onset = None
    pause_id = None
    quiet = ticks = pause_frames = 0
    attempted = speaking_before = False
    try:
        async for pcm in source:
            ticks += 1
            if pause_onset is not None and playback.device.pause_callback is not None:
                emit("pause_timing", id=pause_id, ms=round(
                    1000 * (playback.device.pause_callback - pause_onset)))
                pause_onset = None
            if ticks % 8 == 0:
                playback.observe_output()
                samples = memoryview(pcm).cast("h")
                emit("level", peak=max(max(samples), -min(samples)))
            state = await vad.analyze_audio(pcm)
            if after_gap:
                quiet = quiet + 1 if state == VADState.QUIET else 0
                if quiet >= 20:
                    after_gap = False
                    quiet = 0
                continue
            u = stream.current
            if u is None:
                preroll.append(pcm)
                if state != VADState.SPEAKING:
                    continue
                speaking_before = bool(playback.task and not playback.task.done())
                # Acknowledgments often start just after the speaker finishes.
                # A question or spoken approval still gets its ordinary answer.
                recent_reply = playback.allow_cue and time.monotonic() - playback.last_reply_end < 2
                playback.hold(True)
                if (speaking_before and isinstance(playback.device, Devices)
                        and 0 <= playback.device.capture_time - playback.device.last_audible <= .08):
                    pause_onset = playback.device.capture_time
                    with playback.device.lock:
                        playback.device.pause_callback = None
                        playback.device.pause_requested = True
                near.start(time.monotonic(), playback.device.last_audible if playback.device else 0.)
                u = await stream.begin()
                pause_id = u.id
                emit("onset", id=u.id)
                evidence.clear()
                for frame in preroll:
                    evidence.append(frame)
                    await stream.audio(frame)
                preroll.clear()
                quiet = pause_frames = 0
                attempted = False
                complete = None
                continue

            evidence.append(pcm)
            if playback.device:
                near.observe(playback.device.capture_time, state == VADState.SPEAKING)
            await stream.audio(pcm)
            # Silero enters STOPPING before its silence debounce finishes. A short
            # acoustic gap plus an unfinished interim can cue the listener while
            # Deepgram is still revising words. Endpoints retain their own clock.
            in_pause = state in (VADState.STOPPING, VADState.QUIET)
            pause_frames = pause_frames + 1 if in_pause else 0
            if not in_pause:
                probe_gap = None
            if probe is not None and probe.done():
                predicted_end = probe.result()
                probe = None
                if probe_gap == u.id and pause_frames <= 20 and not predicted_end:
                    playback.acknowledge(u, "early_smart_turn", pause_frames)
            if (3 <= pause_frames <= 20 and not speaking_before and near.clear and playback.device
                    and playback.allow_cue):
                partial = getattr(u, "text", "").strip()
                if unfinished_clause(partial):
                    playback.acknowledge(u, "asr_partial", pause_frames)
                elif (partial and probe is None and decision is None and probed_item != u.id
                      and playback.cues.eligible(u.id, partial, u.frames, now=time.monotonic())):
                    # At most one extra, single-CPU Smart Turn pass per utterance.
                    # It can suggest a cue, but cannot finalize the ASR or run a tool.
                    probed_item = probe_gap = u.id
                    probe = asyncio.create_task(smart(b"".join(evidence)))
            if state != VADState.QUIET:
                if playback.device and not in_pause:
                    playback.quiet_cue()
                quiet = 0
                attempted = False
                complete = None
                if decision is not None:
                    decision.cancel()
                    await asyncio.gather(decision, return_exceptions=True)
                    decision = None
            else:
                if quiet == 0:
                    vad_end = playback.device.capture_time if playback.device else time.monotonic()
                quiet += 1
                if quiet == 1 and not speaking_before and u.frames >= 80:
                    flush = getattr(stream, "flush_words", None)
                    if flush:
                        await flush()
                if not attempted and quiet >= 12:
                    attempted = True
                    decision = asyncio.create_task(smart(b"".join(evidence)))
            if decision is not None and decision.done():
                complete = decision.result()
                decision = None
            if complete is not None:
                partial = getattr(u, "text", "").strip()
                thinking = HESITATION.fullmatch(partial)
                open_clause = unfinished_clause(partial)
                # Deepgram segment time includes preroll; discount the 200 ms
                # Silero stop delay. Parakeet supplies only transcript revisions.
                speech_end = u.frames - quiet - 10
                words_pending = getattr(u, "finalized_frames", speech_end) < speech_end - 1
                hold = not speaking_before and (
                    (words_pending and u.frames >= 80 and quiet < 55)
                    or ((thinking or open_clause) and quiet < 100)
                )
                if complete and not hold:
                    final = await stream.finish()
                    listener_only = final and (
                        HESITATION.fullmatch(final)
                        or (not getattr(playback, "awaiting_answer", False) and is_listening_receipt(final))
                        or ((speaking_before or recent_reply) and is_acknowledgment(final))
                    )
                    if final and near.clear and not listener_only:
                        await playback.cut()
                        emit("commit", id=u.id, text=final, epoch=playback.epoch,
                             vad_end=vad_end, final_at=time.monotonic())
                    else:
                        playback.hold(False)
                        reason = "overlap unconfirmed" if not near.clear else "empty or backchannel"
                        emit("discard", id=u.id, reason=reason)
                    continue
                if (not speaking_before and near.clear and playback.device and quiet <= 60
                        and (not complete or open_clause)):
                    playback.acknowledge(u, "turn_incomplete", pause_frames)
            quiet_limit = 500 if not speaking_before and near.clear and getattr(u, "text", "") else 150
            if quiet >= quiet_limit or u.frames >= 5850:
                await stream.finish(cancel=True)
                playback.hold(False)
                emit("discard", id=u.id, reason="local turn incomplete or time limit")
                after_gap = state != VADState.QUIET
                quiet = 0
                if decision:
                    decision.cancel()
                    await asyncio.gather(decision, return_exceptions=True)
                    decision = None
    finally:
        for pending in (decision, probe):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def commands(playback):
    reader = asyncio.StreamReader(limit=65536)
    pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    try:
        while line := await reader.readline():
            c = json.loads(line)
            if c.get("op") == "close":
                return
            if c.get("op") == "listener":
                playback.allow_cue = c.get("enabled") is True
                playback.awaiting_answer = c.get("awaiting_answer") is True
                if not playback.allow_cue:
                    playback.quiet_cue()
            if c.get("op") == "say" and c.get("idle_only") and (
                    playback.held or (playback.task and not playback.task.done())):
                emit("deferred", receipt=c.get("receipt"))
                continue
            if (c.get("op") == "say" and playback.device and c.get("epoch") == playback.epoch
                    and isinstance(c.get("text"), str) and 0 < len(c["text"]) <= 4000):
                if playback.task and not playback.task.done():
                    if not playback.idle_output:
                        emit("deferred", receipt=c.get("receipt"))
                        continue
                    # An available foreground answer supersedes an incidental cue.
                    playback.task.cancel()
                    await asyncio.gather(playback.task, return_exceptions=True)
                    playback.device.clear()
                    emit("deferred", receipt=playback.receipt)
                playback.idle_output = c.get("idle_only") is True
                playback.task = asyncio.create_task(
                    playback.speak(c["text"], c.get("question"), c.get("receipt"),
                                   cached=c.get("cached") is True)
                )
    finally:
        pipe.close()


async def run(fixture=None, after_gap=False):
    import aiohttp
    factory = Stream
    if os.environ.get("ME3_LIVE_BENCHMARK") == "1":
        from me3.deepgram import DeepgramStream
        factory = DeepgramStream
        token = os.environ.get("DEEPGRAM_API_KEY", "").strip()
        if not token:
            raise ValueError("Set DEEPGRAM_API_KEY in the client .env")
    else:
        token = credential()
    async with aiohttp.ClientSession() as client:
        stream = factory(client, emit, token)
        device = playback = smart = vad = None
        tasks = []
        try:
            await stream.connect()
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams
            vad = SileroVADAnalyzer(params=VADParams(
                confidence=.7, start_secs=.096, stop_secs=.2, min_volume=.5))
            vad.set_sample_rate(16000)
            smart = SmartTurn()
            digital_url = os.environ.get("ME3_FDBENCH_URL")
            if digital_url:
                from integrations.fdbench_pi import DigitalDevice, loopback_audio_url
                if fixture or os.environ.get("ME3_LIVE_BENCHMARK") != "1":
                    raise ValueError("fdbench requires the Pi live benchmark profile")
                device = DigitalDevice()
            elif not fixture:
                indices = [os.environ.get(name) for name in
                           ("ME3_MIC_DEVICE_INDEX", "ME3_SPEAKER_DEVICE_INDEX")]
                mic, speaker = [int(index) if index else None for index in indices]
                device = Devices(frames=480, queue_frames=100, input_index=mic, output_index=speaker)
            playback = Playback(device)
            if digital_url:
                ws = await client.ws_connect(loopback_audio_url(digital_url), max_msg_size=65536)
            emit("ready", fixture=bool(fixture), digital=bool(digital_url))
            tasks = [asyncio.create_task(local_turns(
                stream, device.frames() if digital_url else frames(device, fixture),
                vad, smart, playback, after_gap=after_gap)),
                asyncio.create_task(commands(playback))]
            if digital_url:
                tasks.append(asyncio.create_task(device.receive(ws)))
            done, _ = await asyncio.wait([*tasks, stream.fault], return_when=asyncio.FIRST_COMPLETED)
            if stream.fault in done:
                raise stream.fault.result()
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await stream.close()
            if playback:
                await playback.cut()
                await playback.engine.close()
            if device:
                device.close()
            if smart:
                await smart.close()
            if vad:
                await vad.cleanup()


if __name__ == "__main__":
    import aiohttp
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--after-gap", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.fixture, args.after_gap))
    except PermissionError as exc:
        emit("error", message=str(exc))
        sys.exit(1)
    except (ConnectionError, TimeoutError, aiohttp.ClientConnectionError) as exc:
        emit("error", message=str(exc) or "Parakeet connection timed out")
        sys.exit(os.EX_TEMPFAIL)
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(1)
