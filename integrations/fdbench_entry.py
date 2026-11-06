"""Use with FDBENCH_ENTRY; never inspect benchmark labels or trial metadata."""

import os
from pathlib import Path

PROJECT_MARKER = "me3/duplex_voice.py"


def audio_rates() -> tuple[int, int]:
    return 16000, 24000


async def build(transport, log_dir: Path):
    from me3.duplex_voice import build as build_voice

    # One declared profile for the entire course run, never per-clip labels.
    profile = os.environ.get("ME3_BENCHMARK_PROFILE", "course")
    try:
        from fdbench_marks import mark
    except ModuleNotFoundError as exc:
        if exc.name != "fdbench_marks":
            raise
        # Older benchmark versions have no stage protocol. This only disables
        # optional telemetry; real inference and all safety gates stay intact.
        mark = None
    return await build_voice(
        transport, log_dir, profile=profile, on_stage=mark
    )


def describe() -> dict:
    return {
        "ASR": os.environ.get("ME3_ASR_MODEL"),
        "LLM": os.environ.get("ME3_FOREGROUND_MODEL"),
        "TTS": os.environ.get("ME3_TTS_MODEL"),
        "voice": os.environ.get("ME3_TTS_VOICE"),
        "VAD": "Silero",
        "turn": "SmartTurn v3.2",
    }
