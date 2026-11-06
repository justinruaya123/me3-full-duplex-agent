"""Bounded private Kokoro profiling; plan/self-check import no native libraries.

Use the speech Python. Native/HTTP actions require an explicit subcommand.
The native child is killed after --deadline seconds, including load and warmup.
No production source, model weights, voice, speed or synthesis text is modified.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import inspect
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import urllib.parse
import urllib.request
import wave
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


MODEL = "mlx-community/Kokoro-82M-bf16"
VOICE = "af_heart"
RATE = 24000
MAX_PCM = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
VARIANTS = ("bulk-durations", "cached-voice", "bulk-timestamps")


@dataclass(frozen=True)
class Case:
    name: str
    parts: tuple[str, ...]

    @property
    def text(self):
        return " ".join(self.parts)


CASES = (
    Case("brief", ("The ledger is ready.",)),
    Case("medium", (
        "The schedule is ready,",
        "and the final session begins tomorrow morning.",
    )),
    Case("numbers", (
        "The balance is 1,234.56 dollars,",
        "and the next payment arrives on November 12.",
    )),
    Case("long", (
        "The monitor reports steady progress,",
        "and the current measurements remain within the expected range;",
        "the final chart will include the morning sample and the evening sample.",
    )),
    Case("extended", (
        "The archive contains the field notes from the northern station,",
        "and each folder includes the original measurements together with a short explanation;",
        "the next review will compare rainfall, wind direction, and the condition of the soil before the team chooses another location.",
    )),
)


def compact(text):
    return "".join(text.split())


def changed_source(source, variant):
    """One guarded diagnostic-only change to the installed method source."""
    source = textwrap.dedent(source)
    if variant == "bulk-durations":
        old = "for i, n in enumerate(pred_dur):"
        new = "for i, n in enumerate(pred_dur.tolist()):"
    elif variant == "cached-voice":
        old = "pipeline.voices = {}  # Reset voices"
        new = "# Diagnostic only: retain the exact already loaded voice pack."
    elif variant == "bulk-timestamps":
        old = "MAGIC_DIVISOR = 80"
        new = "pred_dur = pred_dur.tolist()\n    MAGIC_DIVISOR = 80"
    else:
        raise ValueError("Unknown diagnostic variant")
    if source.count(old) != 1:
        raise RuntimeError("Installed Kokoro source differs from the inspected version")
    source = source.replace(old, new)
    if variant == "bulk-timestamps":
        source = source.replace("pred_dur[i:j].sum().item()", "sum(pred_dur[i:j])")
        source = source.replace(".item()", "")
    ast.parse(source)
    return source


@contextmanager
def variant_patch(variant, model_class, pipeline_class):
    if variant == "baseline":
        yield
        return
    owner = pipeline_class if variant == "bulk-timestamps" else model_class
    method = {
        "bulk-durations": "__call__",
        "cached-voice": "generate",
        "bulk-timestamps": "join_timestamps",
    }[variant]
    original = owner.__dict__[method]
    function = original.__func__ if isinstance(original, classmethod) else original
    namespace = {}
    source = changed_source(inspect.getsource(function), variant)
    exec(compile(source, f"<private-{variant}>", "exec"), function.__globals__, namespace)
    with patch.object(owner, method, namespace[method]):
        yield


class Stages:
    """Inclusive timings: child durations must not be added to parent durations."""

    def __init__(self):
        self.events = []
        self.segments = []

    def wrapped(self, name, function):
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                self.events.append({
                    "stage": name,
                    "seconds": time.perf_counter() - started,
                })
        return measured

    @contextmanager
    def collect(self, model, mx):
        from mlx_audio.tts.models.kokoro.pipeline import KokoroPipeline

        pipeline = model._get_pipeline("a")
        original_call = KokoroPipeline.__call__
        original_join = KokoroPipeline.join_timestamps

        def pipeline_call(instance, *args, **kwargs):
            for segment in original_call(instance, *args, **kwargs):
                self.segments.append({
                    "graphemes": segment.graphemes,
                    "phonemes": segment.phonemes,
                    "phoneme_count": len(segment.phonemes),
                    "tokens": [{"text": token.text, "phonemes": token.phonemes}
                               for token in (segment.tokens or [])],
                })
                yield segment

        def join_timestamps(cls, *args, **kwargs):
            return self.wrapped("token_timestamps", original_join)(*args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, "g2p", self.wrapped("g2p", pipeline.g2p)))
            stack.enter_context(patch.object(KokoroPipeline, "load_single_voice", self.wrapped("voice_load", KokoroPipeline.load_single_voice)))
            stack.enter_context(patch.object(type(model), "__call__", self.wrapped("model_forward_including_eval", type(model).__call__)))
            stack.enter_context(patch.object(KokoroPipeline, "join_timestamps", classmethod(join_timestamps)))
            stack.enter_context(patch.object(KokoroPipeline, "__call__", pipeline_call))
            stack.enter_context(patch.object(mx, "clear_cache", self.wrapped("clear_cache", mx.clear_cache)))
            yield


class ForwardLines:
    """Separate diagnostic pass; line tracing perturbs latency and is labelled."""

    def __init__(self, function):
        source, line = inspect.getsourcelines(function)
        self.code = function.__code__
        self.phases = {}
        phase = "graph_to_duration"
        for offset, text in enumerate(source):
            if "indices_list = []" in text:
                phase = "duration_scalar_reads_and_indices"
            elif "indices = mx.concatenate" in text:
                phase = "alignment_and_decoder_graph"
            elif "mx.eval(audio, pred_dur)" in text:
                phase = "audio_eval"
            elif "return self.Output(audio=audio" in text:
                phase = "return"
            self.phases[line + offset] = phase
        self.previous = None
        self.last = None
        self.seconds = {}

    def trace(self, frame, event, arg):
        if frame.f_code is not self.code:
            return None
        now = time.perf_counter()
        if self.previous is not None:
            phase = self.phases.get(self.previous, "other")
            self.seconds[phase] = self.seconds.get(phase, 0) + now - self.last
        self.previous = frame.f_lineno if event == "line" else None
        self.last = now
        return self.trace


def native_sample(model, text, mx, np):
    """Same generation and PCM conversion as MLXSpeechModels, without HTTP."""
    started = time.perf_counter()
    first = None
    pcm = bytearray()
    floats, tokens, conversion = [], [], 0.0
    iterator = model.generate(text=text, voice=VOICE, speed=1.0, lang_code="a")
    try:
        for result in iterator:
            if result.sample_rate != RATE:
                raise ValueError("Unexpected Kokoro sample rate")
            conversion_started = time.perf_counter()
            audio = np.asarray(result.audio)
            if audio.ndim != 1 or not audio.size:
                raise ValueError("Expected nonempty mono audio")
            part = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
            conversion += time.perf_counter() - conversion_started
            if first is None:
                first = time.perf_counter() - started
            if not np.isfinite(audio).all():
                raise ValueError("Expected finite audio samples")
            if len(pcm) + len(part) > MAX_PCM:
                raise ValueError("PCM exceeded the service's bounded output limit")
            pcm.extend(part)
            floats.append(audio.copy())
            tokens.append(result.token_count)
    finally:
        iterator.close()
    if first is None or not any(pcm):
        raise ValueError("Kokoro returned no non-silent PCM")
    record = {
        "first_pcm_seconds": first,
        "total_seconds": time.perf_counter() - started,
        "pcm_conversion_seconds": conversion,
        "audio_seconds": len(pcm) / (RATE * 2),
        "pcm_bytes": len(pcm),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "segment_phoneme_counts": tokens,
    }
    return record, bytes(pcm), floats


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm)


def run_native(args):
    # This function only runs inside the explicit native child.
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.models.kokoro.kokoro import Model
    from mlx_audio.tts.models.kokoro.pipeline import KokoroPipeline
    from mlx_audio.tts.utils import load_model

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = load_model(MODEL)
    load_seconds = time.perf_counter() - started
    warmup, _, _ = native_sample(model, "The instruments are ready.", mx, np)
    report = {
        "kind": "real native Kokoro synthetic development speech; no acoustic device",
        "model": MODEL, "voice": VOICE, "speed": 1.0, "sample_rate": RATE,
        "versions": {name: importlib.metadata.version(name) for name in ("mlx-audio", "mlx", "misaki")},
        "load_seconds": load_seconds, "warmup": warmup,
        "timing_instrumentation": "none in paired timing; separate stage/line passes",
        "trials": [], "profiles": [], "passed": True,
    }
    snapshot = Path(model.config.model_path)
    report["loaded_snapshot"] = str(snapshot)
    voice_path = snapshot / "voices" / f"{VOICE}.safetensors"
    report["voice_sha256"] = hashlib.sha256(voice_path.read_bytes()).hexdigest()
    report["source_sha256"] = {
        "forward": hashlib.sha256(inspect.getsource(Model.__call__).encode()).hexdigest(),
        "generation": hashlib.sha256(inspect.getsource(Model.generate).encode()).hexdigest(),
        "timestamps": hashlib.sha256(inspect.getsource(KokoroPipeline.join_timestamps).encode()).hexdigest(),
    }
    for case_index, case in enumerate(CASES):
        for repeat in range(args.repeats):
            for candidate in args.variants:
                pair = {}
                order = ("baseline", candidate) if repeat % 2 == 0 else (candidate, "baseline")
                for variant in order:
                    mx.random.seed(231000 + case_index)
                    with variant_patch(variant, Model, KokoroPipeline):
                        record, pcm, audio = native_sample(model, case.text, mx, np)
                    pair[variant] = (record, pcm, audio)
                baseline, candidate_result = pair["baseline"], pair[candidate]
                equal_pcm = baseline[1] == candidate_result[1]
                equal_audio = len(baseline[2]) == len(candidate_result[2]) and all(
                    before.dtype == after.dtype and np.array_equal(before, after)
                    for before, after in zip(baseline[2], candidate_result[2])
                )
                equal_tokens = baseline[0]["segment_phoneme_counts"] == candidate_result[0]["segment_phoneme_counts"]
                trial = {
                    "case": case.name, "text": case.text, "text_chars": len(case.text),
                    "repeat": repeat, "variant": candidate, "order": order,
                    "baseline": baseline[0], "candidate": candidate_result[0],
                    "exact_float_audio": equal_audio, "exact_pcm": equal_pcm,
                    "exact_phoneme_counts": equal_tokens,
                }
                report["trials"].append(trial)
                report["passed"] = report["passed"] and equal_pcm and equal_audio and equal_tokens
                if repeat == 0:
                    write_wav(output / f"{case.name}-{candidate}.wav", candidate_result[1])
        stages = Stages()
        mx.random.seed(231000 + case_index)
        with stages.collect(model, mx):
            record, pcm, _ = native_sample(model, case.text, mx, np)
        coverage = compact(case.text) == compact(" ".join(segment["graphemes"] for segment in stages.segments))
        profile = {
            "case": case.name, "text_chars": len(case.text),
            "phoneme_count": sum(segment["phoneme_count"] for segment in stages.segments),
            "record": record, "inclusive_stage_events": stages.events,
            "generated_segments": stages.segments, "complete_input_graphemes": coverage,
        }
        report["profiles"].append(profile)
        report["passed"] = report["passed"] and coverage
        write_wav(output / f"{case.name}-baseline.wav", pcm)
        (output / "native.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ForwardLines(Model.__call__)
    previous_trace = sys.gettrace()
    try:
        sys.settrace(lines.trace)
        record, _, _ = native_sample(model, CASES[-1].text, mx, np)
    finally:
        sys.settrace(previous_trace)
    report["line_profile"] = {
        "case": CASES[-1].name, "perturbs_latency": True,
        "record": record, "forward_phase_seconds": lines.seconds,
    }
    report["coverage_limit"] = "Exact baseline audio equality and complete source graphemes; audition files before claiming pronunciation quality. No ASR scoring or acoustic capture."
    (output / "native.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "pairs": len(report["trials"]), "profiles": len(report["profiles"]), "output": str(output / "native.json")}))
    return 0 if report["passed"] else 1


def run_http(args):
    base = os.environ.get("ME3_TTS_BASE_URL", "").rstrip("/")
    token = os.environ.get("ME3_TTS_API_KEY", "")
    if not token or urllib.parse.urlparse(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Explicit authenticated loopback TTS settings required")
    if os.environ.get("ME3_TTS_MODEL") != MODEL or os.environ.get("ME3_TTS_VOICE") != VOICE:
        raise ValueError("Environment model/voice must equal the fixed investigation selection")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"kind": "actual local HTTP first PCM on generated development sentences; no acoustic device", "model": MODEL, "voice": VOICE, "trials": []}
    for repeat in range(args.repeats):
        for case in CASES:
            body = json.dumps({"model": MODEL, "voice": VOICE, "input": case.text, "response_format": "pcm"}).encode()
            request = urllib.request.Request(base + "/audio/speech", data=body, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=60) as response:
                headers_seconds = time.perf_counter() - started
                if response.headers.get("X-Audio-Sample-Rate") != str(RATE):
                    raise ValueError("Missing or incorrect HTTP PCM sample rate")
                pcm = bytearray(response.read(2))
                first = time.perf_counter() - started
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    pcm.extend(chunk)
                    if len(pcm) > MAX_PCM:
                        raise ValueError("HTTP PCM limit exceeded")
            if not pcm or len(pcm) % 2 or not any(pcm) or pcm.startswith(b"RIFF"):
                raise ValueError("Invalid raw PCM16")
            report["trials"].append({"case": case.name, "text": case.text, "text_chars": len(case.text), "repeat": repeat, "headers_seconds": headers_seconds, "first_pcm_seconds": first, "total_seconds": time.perf_counter() - started, "pcm_bytes": len(pcm), "audio_seconds": len(pcm) / (RATE * 2), "pcm_sha256": hashlib.sha256(pcm).hexdigest()})
            if repeat == 0:
                write_wav(output / f"{case.name}-http.wav", pcm)
            (output / "http.json").write_text(json.dumps(report, indent=2) + "\n")
    report["coverage_limit"] = "HTTP provides PCM only; complete text/phoneme coverage is checked in paired native profiles, and saved WAVs require audition. No ASR or pronunciation-quality claim."
    (output / "http.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"requests": len(report["trials"]), "output": str(output / "http.json")}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "native", "http", "_native", "_http"), default="plan", nargs="?")
    parser.add_argument("--output", default=str(ROOT / "run"))
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=2)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--deadline", type=int, default=240)
    args = parser.parse_args()
    if not 30 <= args.deadline <= 600:
        parser.error("deadline must be between 30 and 600 seconds")
    if args.mode == "plan":
        if any(compact(case.text) != compact(" ".join(case.parts)) for case in CASES):
            raise RuntimeError("Development text coverage failed")
        print(json.dumps({"mode": "plan-only; no native imports or network calls", "model": MODEL, "voice": VOICE, "speed": 1.0, "cases": [{"name": case.name, "chars": len(case.text), "text": case.text, "natural_parts": case.parts} for case in CASES], "variants": args.variants, "paired_requests": len(CASES) * args.repeats * len(args.variants) * 2, "separate_profile_requests": len(CASES) + 1, "warmup_requests": 1, "bounded_wall_seconds": args.deadline}, indent=2))
        return 0
    if args.mode == "_native":
        return run_native(args)
    if args.mode == "_http":
        return run_http(args)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "_" + args.mode, "--output", str(output), "--repeats", str(args.repeats), "--variants", *args.variants]
    environment = dict(os.environ, HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    with (output / f"{args.mode}.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
        try:
            return child.wait(timeout=args.deadline)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise TimeoutError("Private profiler deadline exceeded; native child reaped") from None
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
