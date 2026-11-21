"""Optional Pipecat wiring; module import does not load audio models."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

PIPECAT_REVISION = "6f777a0ef3bb98163d10d708525a0db21cda5fbf"


def settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if env is None else env
    from me3.local_tts import BUNDLE, DEFAULT_DIR, VOICE

    backend = values.get("ME3_TTS_BACKEND", "local")
    if backend not in {"local", "server"}:
        raise ValueError("ME3_TTS_BACKEND must be local or server")
    result = {"tts_backend": backend}
    if backend == "local":
        result.update(tts_model=BUNDLE, tts_voice=VOICE,
                      tts_model_dir=values.get("ME3_KOKORO_DIR", DEFAULT_DIR))
    else:
        voice = values.get("ME3_TTS_VOICE")
        if not voice:
            raise ValueError("Set ME3_TTS_VOICE for server synthesis")
        result["tts_voice"] = voice
    for kind in (("asr", "tts") if backend == "server" else ("asr",)):
        prefix = "ME3_" + kind.upper()
        model = values.get(prefix + "_MODEL", "")
        url_text = values.get(prefix + "_BASE_URL", "")
        if not model or not url_text:
            raise ValueError("Set " + prefix + "_MODEL and " + prefix + "_BASE_URL")
        result[kind + "_model"] = model
        result[kind + "_base_url"] = url_text
        result[kind + "_key"] = values.get(prefix + "_API_KEY", "")
        url = urlparse(url_text)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Inference endpoints must be HTTP(S) base URLs")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Credentials must not appear in speech URLs")
        if not result[kind + "_key"].strip():
            raise ValueError(prefix + "_API_KEY is required for speech authentication")
    return result


async def build(transport, log_dir: Path, **options):
    from me3.audio_pipeline import build as build_pipeline

    return await build_pipeline(transport, log_dir, **options)


def main() -> None:
    import sys

    from me3.runtime import main as runtime_main

    if "--voice" not in sys.argv:
        sys.argv.append("--voice")
    runtime_main()


if __name__ == "__main__":
    main()
