"""Probe the selected TTS route through the voice adapter, without playback."""

import asyncio
import hashlib
import platform
import sys
import time

from me3.audio_pipeline import ConfiguredSpeech
from me3.duplex_voice import settings


async def probe(*, roundtrip=False) -> dict:
    import resource

    config = settings()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    speech = ConfiguredSpeech(config)
    rows = []
    recognition = None
    sentence = "The local speech check is ready."
    try:
        for state in ("cold_client", "warm_client"):
            begin = time.monotonic()
            await speech.start()
            first = None
            digest = hashlib.sha256()
            size = 0
            nonzero = False
            recording = bytearray()
            async for pcm in speech.synthesize(sentence):
                if first is None:
                    first = time.monotonic() - begin
                if roundtrip and state == "warm_client":
                    recording.extend(pcm)
                nonzero |= any(pcm)
                size += len(pcm)
                digest.update(pcm)
            elapsed = time.monotonic() - begin
            if not size or not nonzero:
                raise ValueError("TTS produced empty or silent PCM")
            rows.append(
                dict(
                    state=state,
                    first_pcm_seconds=first,
                    pcm_bytes=size,
                    audio_seconds=size / 48000,
                    seconds=elapsed,
                    rtf=elapsed / (size / 48000),
                    sha256=digest.hexdigest(),
                )
            )
        if roundtrip:
            import soxr
            import numpy as np
            from me3.capture import wav16

            audio = soxr.resample(np.frombuffer(recording, dtype="<i2"), 24000, 16000)
            begin = time.monotonic()
            transcript = await speech.transcribe(
                wav16(np.clip(audio, -32768, 32767).astype("<i2").tobytes())
            )
            recognition = dict(
                expected=sentence,
                transcript=transcript,
                seconds=time.monotonic() - begin,
                model=config["asr_model"],
            )
    finally:
        await speech.close()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "kind": "two synthesis requests; software PCM; playback devices closed",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "backend": config["tts_backend"],
        "model": config["tts_model"],
        "voice": config["tts_voice"],
        "rows": rows,
        "child_peak_rss_bytes": (
            usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
            if config["tts_backend"] == "local"
            else None
        ),
        "child_cpu_seconds": (
            usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime
            if config["tts_backend"] == "local"
            else None
        ),
        "synthetic_asr": recognition,
    }


if __name__ == "__main__":
    import json
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roundtrip",
        action="store_true",
        help="Send synthetic audio to configured Whisper",
    )
    options = parser.parse_args()
    print(json.dumps(asyncio.run(probe(roundtrip=options.roundtrip)), indent=2))
