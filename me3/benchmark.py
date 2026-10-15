"""
Reproducible simulator-only control-path measurements, not acoustic latency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import platform
import time
from pathlib import Path

from .core import Controller, Supervisor


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def benchmark(output: Path, trials: int = 20) -> dict:
    if not 1 <= trials <= 1000:
        raise ValueError("trials must be between 1 and 1000.")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "backend": "mock", "hardware_qualified": False,
        "measurement": "monotonic request-to-text, artificial model delays",
        "audio_devices_used": False, "python": platform.python_version(),
        "platform": platform.platform(), "trials_per_track": trials,
        "percentile_method": "nearest rank", "tracks": {},
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.glob("*.py"))
        },
    }

    class ControlledBackend:
        async def run(self, prompt, workspace, *, foreground=False):
            await asyncio.sleep(0.01 if foreground else 3600)
            return "simulated response"

    records = []
    for workers in (0, 1):
        backend = ControlledBackend()
        supervisor = Supervisor(output / f"workers-{workers}", backend)
        controller = Controller(supervisor, backend)
        latencies = []
        try:
            if workers:
                supervisor.submit("Artificially blocked worker")
                await asyncio.sleep(0)
            for trial in range(trials):
                start = time.monotonic_ns()
                record = {
                    "workers": workers, "trial": trial, "start_ns": start,
                }
                try:
                    await controller.ask("Foreground probe")
                    elapsed = (time.monotonic_ns() - start) / 1e6
                    latencies.append(elapsed)
                    record.update(success=True, request_to_text_ms=elapsed)
                except Exception as exc:
                    record.update(success=False, error_type=type(exc).__name__)
                records.append(record)
            report["tracks"][f"workers_{workers}"] = {
                "successes": len(
                    latencies,
                ), "failures": trials - len(latencies),
                "request_to_text_p50_ms": percentile(latencies, 0.5),
                "request_to_text_p95_ms": percentile(latencies, 0.95),
            }
        finally:
            await controller.close()
            await supervisor.close()
    a, b = (
        report["tracks"][f"workers_{n}"]["request_to_text_p95_ms"]
        for n in (0, 1)
    )
    report["foreground_p95_degradation_ms"] = (
        None if a is None or b is None else b - a
    )
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "trials.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    return report
