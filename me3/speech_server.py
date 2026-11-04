"""Separate authenticated M2 service: MLX Whisper and Kokoro, no orchestration."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import io
import os
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeechServerConfig:
    asr_model: str
    tts_model: str
    voice: str
    token: str = field(repr=False)

    def __post_init__(self):
        if not all((self.asr_model, self.tts_model, self.voice, self.token)):
            raise ValueError(
                "Explicit ASR/TTS models, voice and server token required"
            )


class MLXSpeechModels:
    """One bounded executor per role; MLX never loads in the portable runtime."""

    def __init__(self, config: SpeechServerConfig):
        self.config = config
        self.asr_executor = ThreadPoolExecutor(max_workers=1)
        self.tts_executor = ThreadPoolExecutor(max_workers=1)
        self.tts_model = None
        self._native_futures = {}

    def busy(self, role: str) -> bool:
        future = self._native_futures.get(role)
        return future is not None and not future.done()

    async def _native(self, role: str, function, *args):
        if self.busy(role):
            raise RuntimeError("Native speech role remains busy")
        executor = self.asr_executor if role == "asr" else self.tts_executor
        future = executor.submit(function, *args)
        self._native_futures[role] = future
        # Retain the concurrent future: cancelling an async HTTP waiter cannot
        # stop a running GPU/thread call, and must not admit another queued call.
        return await asyncio.wrap_future(future)

    async def transcribe(self, pcm: bytes) -> dict:
        def infer():
            import mlx_whisper
            import numpy as np

            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            result = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=self.config.asr_model,
                word_timestamps=True,
                verbose=False,
            )
            return {
                "text": result["text"],
                "segments": result.get("segments", []),
            }

        return await self._native("asr", infer)

    async def synthesize(self, text: str):
        def begin():
            from mlx_audio.tts.utils import load_model

            if self.tts_model is None:
                self.tts_model = load_model(self.config.tts_model)
            return iter(
                self.tts_model.generate(
                    text=text,
                    voice=self.config.voice,
                    speed=1.0,
                    lang_code="a",
                )
            )

        def next_pcm(iterator):
            import numpy as np

            result = next(iterator, None)
            if result is None:
                return None
            if result.sample_rate != 24000:
                raise ValueError(
                    "Kokoro service requires exactly 24kHz output"
                )
            audio = np.asarray(result.audio)
            if audio.ndim != 1:
                raise ValueError("Kokoro output must be mono")
            return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()

        iterator = await self._native("tts", begin)
        while True:
            pcm = await self._native("tts", next_pcm, iterator)
            if pcm is None:
                break
            yield pcm

    async def close(self):
        self.asr_executor.shutdown(wait=False, cancel_futures=True)
        self.tts_executor.shutdown(wait=False, cancel_futures=True)


def create_app(config: SpeechServerConfig, models):
    from aiohttp import web

    asr_lock, tts_lock = asyncio.Lock(), asyncio.Lock()

    @web.middleware
    async def authenticate(request, handler):
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + config.token):
            raise web.HTTPUnauthorized()
        try:
            return await handler(request)
        except (ValueError, KeyError, wave.Error, EOFError):
            raise web.HTTPBadRequest(text="Invalid speech request") from None

    app = web.Application(middlewares=[authenticate], client_max_size=600_000)

    async def catalog(request):
        return web.json_response(
            {"data": [{"id": config.asr_model}, {"id": config.tts_model}]}
        )

    async def transcribe(request):
        if asr_lock.locked() or (
            hasattr(models, "busy") and models.busy("asr")
        ):
            raise web.HTTPServiceUnavailable(text="ASR capacity busy")
        async with asr_lock, asyncio.timeout(60):
            data = await request.post()
            if data.get("model") != config.asr_model:
                raise ValueError("ASR model substitution is disabled")
            content = data["file"].file.read(600001)
            with wave.open(io.BytesIO(content)) as wav:
                if (
                    wav.getnchannels(),
                    wav.getsampwidth(),
                    wav.getframerate(),
                ) != (1, 2, 16000) or not 0 < wav.getnframes() <= 256000:
                    raise ValueError("ASR requires <=16s mono PCM16 at 16kHz")
                pcm = wav.readframes(wav.getnframes())
                if len(pcm) != wav.getnframes() * 2:
                    raise ValueError("Truncated ASR audio")
            return web.json_response(await models.transcribe(pcm))

    async def synthesize(request):
        if tts_lock.locked() or (
            hasattr(models, "busy") and models.busy("tts")
        ):
            raise web.HTTPServiceUnavailable(text="TTS capacity busy")
        async with tts_lock, asyncio.timeout(90):
            data = await request.json()
            if (
                data.get("model") != config.tts_model
                or data.get("voice") != config.voice
                or data.get("response_format") != "pcm"
            ):
                raise ValueError(
                    "TTS model/voice/format differs from configuration"
                )
            text = data.get("input")
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 16000:
                raise ValueError("Invalid TTS text")
            response = web.StreamResponse(
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Audio-Sample-Rate": "24000",
                }
            )
            stream = models.synthesize(text)
            first = await anext(
                stream
            )  # Fail before HTTP 200 on model startup errors.
            try:
                await response.prepare(request)
                total = 0
                for_first = first
                while True:
                    total += len(for_first)
                    if total > 8_388_608 or len(for_first) % 2:
                        raise ValueError("Invalid or oversized PCM stream")
                    await response.write(for_first)
                    for_first = await anext(stream, None)
                    if for_first is None:
                        break
            finally:
                await stream.aclose()
            await response.write_eof()
            return response

    app.router.add_get("/v1/models", catalog)
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    app.router.add_post("/v1/audio/speech", synthesize)

    async def cleanup(app):
        if hasattr(models, "close"):
            await models.close()

    app.on_cleanup.append(cleanup)
    return app


def main():
    from aiohttp import web

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    try:
        config = SpeechServerConfig(
            os.environ.get("ME3_ASR_MODEL", ""),
            os.environ.get("ME3_TTS_MODEL", ""),
            os.environ.get("ME3_TTS_VOICE", ""),
            os.environ.get("ME3_SPEECH_SERVER_TOKEN", ""),
        )
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    web.run_app(
        create_app(config, MLXSpeechModels(config)),
        host=args.host,
        port=args.port,
        access_log=None,
    )


if __name__ == "__main__":
    main()
