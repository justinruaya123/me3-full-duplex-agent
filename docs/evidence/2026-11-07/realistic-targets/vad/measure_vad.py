"""Measure installed CPU Silero on independent digital development inputs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soxr
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState


RATE = 16000
CHUNK = 320
SETTINGS = [
    ("baseline", 0.7, 0.200, 0.6),
    ("start_128", 0.7, 0.128, 0.6),
    ("start_096", 0.7, 0.096, 0.6),
    ("start_064", 0.7, 0.064, 0.6),
    ("confidence_060", 0.6, 0.096, 0.6),
    ("volume_050", 0.7, 0.096, 0.5),
    ("confidence_060_volume_050", 0.6, 0.096, 0.5),
    ("no_volume_diagnostic", 0.7, 0.096, 0.0),
]


@dataclass
class Stimulus:
    name: str
    kind: str
    samples: np.ndarray
    source: str | None = None
    condition: str | None = None
    gain_db: int | None = None
    onset_s: float | None = None
    end_s: float | None = None


class TracedSilero(SileroVADAnalyzer):
    """Observe real installed calculations without replacing detector logic."""

    def __init__(self, params):
        super().__init__(params=params)
        self.windows = []

    def voice_confidence(self, buffer):
        confidence = float(super().voice_confidence(buffer).item())
        self.windows.append({
            "window_end_s": (len(self.windows) + 1) * 512 / RATE,
            "confidence": confidence,
        })
        return confidence

    def _get_smoothed_volume(self, audio):
        volume = float(super()._get_smoothed_volume(audio))
        self.windows[-1]["volume"] = volume
        self.windows[-1]["raw_volume"] = float(self._volume_tracker.volume)
        return volume


def source_audio(path: Path):
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError(f"Expected mono PCM16 WAV: {path}")
        rate = stream.getframerate()
        audio = np.frombuffer(stream.readframes(stream.getnframes()), "<i2")
    samples = audio.astype(np.float64) / 32768
    if rate != RATE:
        samples = soxr.resample(samples, rate, RATE, quality="HQ")
    bins = [
        float(np.sqrt(np.mean(samples[start:start + 160] ** 2)))
        for start in range(0, len(samples), 160)
    ]
    active = [i for i, rms in enumerate(bins) if rms >= 10 ** (-50 / 20)]
    if not active:
        raise ValueError(f"No source energy above -50 dBFS: {path}")
    return samples, active[0] * 0.01, (active[-1] + 1) * 0.01


def normalized_noise(rng, size, rms_db, *, pink=False):
    values = rng.normal(size=size)
    if pink:
        spectrum = np.fft.rfft(values)
        spectrum[1:] /= np.sqrt(np.arange(1, len(spectrum)))
        spectrum[0] = 0
        values = np.fft.irfft(spectrum, n=size)
    values *= 10 ** (rms_db / 20) / np.sqrt(np.mean(values ** 2))
    return values


def stimuli(paths: list[Path]):
    result = []
    sources = []
    for path in paths:
        speech, onset, end = source_audio(path)
        active = speech[int(onset * RATE):int(end * RATE)]
        active_rms = float(np.sqrt(np.mean(active ** 2)))
        sources.append({
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "resampled_duration_s": len(speech) / RATE,
            "reference_onset_s": onset,
            "reference_end_s": end,
            "active_rms_dbfs": 20 * math.log10(active_rms),
        })
        for gain in (0, -6, -12, -18, -24):
            for condition in ("warm_silence", "cold_start", "noise20_snr"):
                prefix = 0 if condition == "cold_start" else int(0.75 * RATE)
                samples = np.concatenate((
                    np.zeros(prefix), speech * 10 ** (gain / 20),
                    np.zeros(RATE),
                ))
                if condition == "noise20_snr":
                    rng = np.random.default_rng(231)
                    noise = rng.normal(size=len(samples))
                    noise *= (
                        active_rms * 10 ** (gain / 20) / 10
                        / np.sqrt(np.mean(noise ** 2))
                    )
                    samples += noise
                result.append(Stimulus(
                    f"{path.stem}/{condition}/gain{gain}", "speech", samples,
                    source=path.stem, condition=condition, gain_db=gain,
                    onset_s=prefix / RATE + onset,
                    end_s=prefix / RATE + end,
                ))
    rng = np.random.default_rng(231)
    size = RATE * 6
    result.append(Stimulus("silence", "negative", np.zeros(size)))
    for rms in (-45, -30, -15):
        result.append(Stimulus(
            f"white_{rms}", "negative", normalized_noise(rng, size, rms)
        ))
    for rms in (-35, -20):
        result.append(Stimulus(
            f"pink_{rms}", "negative",
            normalized_noise(rng, size, rms, pink=True),
        ))
    clicks = np.zeros(size)
    clicks[RATE] = 0.9
    result.append(Stimulus("single_click", "negative", clicks))
    clicks = np.zeros(size)
    for at in range(RATE // 2, size, RATE // 2):
        clicks[at:at + 32] = 0.9 * np.exp(-np.arange(32) / 5)
    result.append(Stimulus("click_train", "negative", clicks))
    bursts = np.zeros(size)
    for at in range(RATE // 2, size, RATE // 2):
        bursts[at:at + 640] = normalized_noise(rng, 640, -15)
    result.append(Stimulus("noise_bursts_40ms", "negative", bursts))
    timeline = np.arange(size) / RATE
    result.append(Stimulus(
        "tone440", "negative", 0.1 * np.sin(2 * np.pi * 440 * timeline)
    ))
    hum = sum(np.sin(2 * np.pi * 60 * h * timeline) / h for h in (1, 2, 3))
    hum *= 10 ** (-25 / 20) / np.sqrt(np.mean(hum ** 2))
    result.append(Stimulus("hum60", "negative", hum))
    for stimulus in result:
        if np.max(np.abs(stimulus.samples)) >= 1:
            raise ValueError(f"Clipping stimulus: {stimulus.name}")
    return result, sources


def statistics(values):
    if not values:
        return None
    return {
        "n": len(values), "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)), "max": max(values),
    }


async def measure(stimulus: Stimulus, setting):
    name, confidence, start, volume = setting
    params = VADParams(
        confidence=confidence, start_secs=start, stop_secs=0.2,
        min_volume=volume,
    )
    loaded = time.perf_counter()
    analyzer = TracedSilero(params)
    analyzer.set_sample_rate(RATE)
    load_s = time.perf_counter() - loaded
    providers = analyzer._model.session.get_providers()
    if providers != ["CPUExecutionProvider"]:
        await analyzer.cleanup()
        raise ValueError(f"Expected CPU only, received {providers}")
    pcm = np.round(stimulus.samples * 32768).astype("<i2").tobytes()
    pcm += b"\0" * ((-len(pcm)) % (CHUNK * 2))
    starts, stops, durations = [], [], []
    terminal = VADState.QUIET
    try:
        for offset in range(0, len(pcm), CHUNK * 2):
            before = time.perf_counter()
            state = await analyzer.analyze_audio(pcm[offset:offset + CHUNK * 2])
            durations.append(time.perf_counter() - before)
            when = (offset // 2 + CHUNK) / RATE
            if state == VADState.SPEAKING and terminal == VADState.QUIET:
                starts.append(when)
                terminal = state
            elif state == VADState.QUIET and terminal == VADState.SPEAKING:
                stops.append(when)
                terminal = state
        windows = analyzer.windows
        first_confidence = next((
            w["window_end_s"] for w in windows
            if w["confidence"] >= confidence
        ), None)
        first_volume = next((
            w["window_end_s"] for w in windows if w["volume"] >= volume
        ), None)
        first_both = next((
            w["window_end_s"] for w in windows
            if w["confidence"] >= confidence and w["volume"] >= volume
        ), None)
        valid = []
        before_speech = []
        if stimulus.onset_s is not None:
            valid = [s for s in starts if stimulus.onset_s <= s <= stimulus.end_s]
            before_speech = [s for s in starts if s < stimulus.onset_s]
        record = {
            "setting": name, "stimulus": stimulus.name, "kind": stimulus.kind,
            "source": stimulus.source, "condition": stimulus.condition,
            "gain_db": stimulus.gain_db,
            "audio_duration_s": len(pcm) / (RATE * 2),
            "reference_onset_s": stimulus.onset_s,
            "reference_end_s": stimulus.end_s,
            "starts_s": starts, "stops_s": stops,
            "pre_speech_starts_s": before_speech,
            "onset_delay_s": (
                valid[0] - stimulus.onset_s if valid else None
            ),
            "first_confidence_crossing_s": first_confidence,
            "first_volume_crossing_s": first_volume,
            "first_joint_crossing_s": first_both,
            "model_load_s": load_s,
            "cpu_service_s": statistics(durations),
            "cpu_total_s": sum(durations),
            "start_frames_32ms": analyzer._vad_start_frames,
            "providers": providers,
        }
        trace = None
        if stimulus.source and stimulus.gain_db in (0, -24) and (
            stimulus.condition in ("warm_silence", "cold_start")
        ):
            trace = {
                "setting": name, "stimulus": stimulus.name,
                "windows": windows,
            }
        return record, trace
    finally:
        await analyzer.cleanup()


def summarize(records):
    result = {}
    for name, *_ in SETTINGS:
        selected = [r for r in records if r["setting"] == name]
        speech = [r for r in selected if r["kind"] == "speech"]
        negative = [r for r in selected if r["kind"] == "negative"]
        exposure = sum(r["audio_duration_s"] for r in negative)
        events = sum(len(r["starts_s"]) for r in negative)
        by_condition = {}
        for condition in ("warm_silence", "cold_start", "noise20_snr"):
            by_condition[condition] = {}
            for gain in (0, -6, -12, -18, -24):
                rows = [r for r in speech if r["condition"] == condition
                        and r["gain_db"] == gain]
                by_condition[condition][str(gain)] = {
                    "n": len(rows),
                    "misses": sum(r["onset_delay_s"] is None for r in rows),
                    "pre_speech_start_trials": sum(
                        bool(r["pre_speech_starts_s"]) for r in rows
                    ),
                    "onset_delay_s": statistics([
                        r["onset_delay_s"] for r in rows
                        if r["onset_delay_s"] is not None
                    ]),
                }
        result[name] = {
            "speech_trials": len(speech),
            "speech_misses": sum(r["onset_delay_s"] is None for r in speech),
            "onset_delay_s": statistics([
                r["onset_delay_s"] for r in speech
                if r["onset_delay_s"] is not None
            ]),
            "negative_trials": len(negative),
            "negative_onset_trials": sum(bool(r["starts_s"]) for r in negative),
            "negative_events": events, "negative_exposure_s": exposure,
            "negative_events_per_min": events / exposure * 60,
            "zero_event_poisson_upper95_per_min": (
                -math.log(0.05) / exposure * 60 if events == 0 else None
            ),
            "by_condition_gain": by_condition,
            "cpu_service_total_s": sum(r["cpu_total_s"] for r in selected),
            "audio_total_s": sum(r["audio_duration_s"] for r in selected),
        }
    return result


async def main(args):
    logger.remove()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    paths = [args.source]
    if args.extra_dir and args.extra_dir.exists():
        paths += sorted(args.extra_dir.glob("*.wav"))
    corpus, sources = stimuli(paths)
    records, traces = [], []
    start = time.perf_counter()
    for index, setting in enumerate(SETTINGS):
        for stimulus in corpus:
            record, trace = await measure(stimulus, setting)
            records.append(record)
            if trace is not None:
                traces.append(trace)
        print(f"completed {setting[0]} ({index + 1}/{len(SETTINGS)})", flush=True)
    import pipecat.audio.vad.silero as silero
    import pipecat.audio.vad.vad_analyzer as vad_analyzer
    import pipecat.audio.volume as volume

    model = Path(silero.__file__).parent / "data/silero_vad.onnx"
    source_files = [Path(silero.__file__), Path(vad_analyzer.__file__),
                    Path(volume.__file__), model, Path(__file__)]
    report = {
        "scope": "actual installed CPU detector; digital, offline sample clock",
        "not_measured": ["ASR", "SmartTurn", "speaker/addressee", "actions",
                         "transport playback", "microphone", "acoustics"],
        "python": sys.version, "platform": platform.platform(),
        "pipecat_version": importlib.metadata.version("pipecat-ai"),
        "onnxruntime_version": importlib.metadata.version("onnxruntime"),
        "soxr_version": importlib.metadata.version("soxr"),
        "seed": 231, "rate": RATE, "chunk_samples": CHUNK,
        "settings": SETTINGS,
        "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in source_files},
        "speech_sources": sources,
        "elapsed_wall_s": time.perf_counter() - start,
        "summary": summarize(records), "records": records,
    }
    (output / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "window-traces.json").write_text(json.dumps(traces, indent=2) + "\n")
    print(json.dumps({name: {key: value for key, value in info.items()
                            if key != "by_condition_gain"}
                      for name, info in report["summary"].items()}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(
        ".local/verification/d2/voice-sample.wav"))
    parser.add_argument("--extra-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
