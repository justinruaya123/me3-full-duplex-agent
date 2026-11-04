"""Use with FDBENCH_ENTRY; never inspect benchmark labels or trial metadata."""

from pathlib import Path

PROJECT_MARKER = "me3/duplex_voice.py"


def audio_rates() -> tuple[int, int]:
    return 16000, 24000


async def build(transport, log_dir: Path):
    from me3.duplex_voice import build as build_voice

    # One declared profile for the entire course run, never per-clip labels.
    import os
    profile = os.environ.get("ME3_BENCHMARK_PROFILE", "course")
    return await build_voice(transport, log_dir, profile=profile)
