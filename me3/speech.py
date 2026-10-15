"""
Inference-only speech adapters and a deliberately simple local energy VAD.
"""

from __future__ import annotations

import io
import math
import os
import struct
import wave
from collections import deque
from contextlib import asynccontextmanager
from urllib.parse import urlsplit


class HTTPSpeech:
    """
    Operator-configured ASR upload and streaming 24 kHz PCM16 TTS endpoints.
    """

    def __init__(
        self, asr_url: str, tts_url: str, asr_model: str, tts_model: str,
        *, voice: str = "alloy", client=None,
    ) -> None:
        for endpoint in (asr_url, tts_url):
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(
                    "Speech endpoints must be absolute HTTP(S) URLs.",
                )
            if parsed.username or parsed.password:
                raise ValueError(
                    "Put authentication in ME3_SPEECH_API_KEY, not URLs.",
                )
        self.asr_url, self.tts_url = asr_url, tts_url
        self.asr_model, self.tts_model = asr_model, tts_model
        self.voice, self.client = voice, client

    @asynccontextmanager
    async def _client(self):
        if self.client is not None:
            yield self.client
            return
        import httpx

        token = os.environ.get("ME3_SPEECH_API_KEY")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=45, headers=headers) as client:
            yield client

    async def transcribe(self, audio: bytes) -> str:
        if len(audio) > 600000:
            raise ValueError("Audio exceeds the preliminary upload limit.")
        try:
            with wave.open(io.BytesIO(audio), "rb") as stream:
                audio_format = (
                    stream.getnchannels(), stream.getsampwidth(),
                    stream.getframerate(),
                )
                if audio_format != (1, 2, 16000):
                    raise ValueError(
                        "ASR input must be mono PCM16 WAV at 16 kHz.",
                    )
                if not 0 < stream.getnframes() <= 16 * 16000:
                    raise ValueError(
                        (
                            "ASR input must be longer than zero and "
                            "at most 16 seconds."
                        ),
                    )
                if len(
                    stream.readframes(stream.getnframes()),
                ) != stream.getnframes() * 2:
                    raise ValueError("Truncated WAV data.")
        except (wave.Error, EOFError) as exc:
            raise ValueError("Invalid WAV input.") from exc
        async with self._client() as client:
            response = await client.post(
                self.asr_url, data={"model": self.asr_model},
                files={"file": ("utterance.wav", audio, "audio/wav")},
            )
            response.raise_for_status()
            text = response.json().get("text")
            if not isinstance(
                text,
                str,
            ) or not text.strip() or len(text) > 16000:
                raise ValueError("ASR returned no valid transcript.")
            return text.strip()

    async def synthesize(self, text: str):
        if not text.strip() or len(text) > 16000:
            raise ValueError("TTS requires 1 to 16000 characters.")
        total = 0
        async with self._client() as client:
            async with client.stream("POST", self.tts_url, json={
                "model": self.tts_model, "input": text,
                "voice": self.voice, "response_format": "pcm",
            }) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(chunk_size=4800):
                    if len(chunk) % 2 or (total == 0 and chunk.startswith(
                        b"RIFF",
                    )):
                        raise ValueError(
                            (
                                "TTS must return raw little-endian PCM16, "
                                "not a WAV."
                            ),
                        )
                    total += len(chunk)
                    if total > 8 * 1024 * 1024:
                        raise ValueError(
                            "TTS exceeded the preliminary audio limit.",
                        )
                    if chunk:
                        yield chunk
        if not total:
            raise ValueError("TTS returned no audio.")


def make_speech(config: dict) -> HTTPSpeech:
    speech = config.get("speech", {})
    required = ("asr_url", "tts_url", "asr_model", "tts_model")
    if not all(speech.get(key) for key in required):
        raise ValueError(
            "Configure speech ASR/TTS URLs and model identifiers first.",
        )
    return HTTPSpeech(
        *(speech[key] for key in required),
        voice=speech.get("voice", "alloy"),
    )


class EnergyVAD:
    """
    20 ms/16 kHz frames. Not semantic endpointing or speaker verification.
    """

    def __init__(
        self, *, threshold: float = 600, start_frames: int = 3,
        silence_frames: int = 30, max_frames: int = 750,
    ) -> None:
        self.threshold = threshold
        self.start_frames, self.silence_frames, self.max_frames = (
            start_frames, silence_frames, max_frames
        )
        self.preroll = deque(maxlen=10)
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.overflowed = False
        self._loud = self._quiet = 0
        self._frames: list[bytes] = []
        self.preroll.clear()

    def feed(self, frame: bytes) -> tuple[bool, bytes | None]:
        if len(frame) != 640:
            raise ValueError("VAD needs exactly 320 PCM16 samples per frame.")
        samples = struct.unpack("<320h", frame)
        loud = math.sqrt(
            sum(value * value for value in samples) / 320,
        ) >= self.threshold
        self._quiet = 0 if loud else self._quiet + 1
        if self.overflowed:
            if self._quiet >= self.silence_frames:
                self.reset()
            return False, None
        started = False
        if not self.active:
            self.preroll.append(frame)
            self._loud = self._loud + 1 if loud else 0
            if self._loud < self.start_frames:
                return False, None
            self.active = started = True
            self._frames = list(self.preroll)
        else:
            self._frames.append(frame)
        if len(self._frames) >= self.max_frames:
            self._frames.clear()
            self.active = False
            self.overflowed = True
            return started, None
        if self._quiet < self.silence_frames:
            return started, None
        output = io.BytesIO()
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"".join(self._frames))
        self.reset()
        return started, output.getvalue()
