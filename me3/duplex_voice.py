"""Optional Pipecat wiring; module import does not load audio models."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

PIPECAT_REVISION = "6f777a0ef3bb98163d10d708525a0db21cda5fbf"


def settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if env is None else env
    names = (
        "ASR_BASE_URL",
        "ASR_MODEL",
        "TTS_BASE_URL",
        "TTS_MODEL",
        "TTS_VOICE",
    )
    if any(not values.get("ME3_" + key) for key in names):
        raise ValueError(
            "Set ME3_ASR/TTS_BASE_URL, MODEL and TTS_VOICE explicitly",
        )
    result = {key.lower(): values["ME3_" + key] for key in names}
    for key in ("asr_base_url", "tts_base_url"):
        url = urlparse(result[key])
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Inference endpoints must be HTTP(S) base URLs")
    result["asr_key"] = values.get("ME3_ASR_API_KEY", "")
    result["tts_key"] = values.get("ME3_TTS_API_KEY", "")
    for kind in ("asr", "tts"):
        url = urlparse(result[kind + "_base_url"])
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Credentials must not appear in speech URLs")
        if url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            if not result[kind + "_key"]:
                raise ValueError("LAN speech endpoints require authentication")
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
