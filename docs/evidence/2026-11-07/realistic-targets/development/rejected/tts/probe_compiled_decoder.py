"""Private decoder-only Kokoro experiment. Default plan mode runs no native code.

Native mode requires the root agent's exclusive GPU slot. The supervisor kills
and reaps its native child after a fixed deadline. No source/model file changes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
import random
import signal
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from profile_tts import CASES, MODEL, ROOT, VOICE, Stages, compact, native_sample
from profile_tts import write_wav


SNAPSHOT = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"


@contextmanager
def owning_decoder(model, decoder):
    """Replace only this loaded owner's callable; always restore its module."""
    original = model.decoder
    try:
        model.decoder = decoder
        yield
    finally:
        model.decoder = original
        if model.decoder is not original:
            raise RuntimeError("Kokoro decoder restoration failed")


def rng_canary(mx, np):
    """Observe the next public draw after inference, outside audio timing."""
    array = np.asarray(mx.random.uniform(shape=(4,)))
    return {"shape": list(array.shape), "dtype": str(array.dtype),
            "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
            "values": array.tolist()}


def compare_audio(before, after, np):
    """Preserve strict failures and raw errors; apply no quality tolerance."""
    before_record, before_pcm, before_audio = before
    after_record, after_pcm, after_audio = after
    shapes_equal = (
        len(before_audio) == len(after_audio)
        and all(a.shape == b.shape for a, b in zip(before_audio, after_audio))
    )
    dtypes_equal = (
        len(before_audio) == len(after_audio)
        and all(a.dtype == b.dtype for a, b in zip(before_audio, after_audio))
    )
    result = {
        "same_shapes": shapes_equal,
        "same_dtypes": dtypes_equal,
        "same_phoneme_counts": (
            before_record["segment_phoneme_counts"]
            == after_record["segment_phoneme_counts"]
        ),
        "same_audio_duration": (
            before_record["audio_seconds"] == after_record["audio_seconds"]
        ),
        "exact_pcm": before_pcm == after_pcm,
        "exact_float_bytes": shapes_equal and dtypes_equal and all(
            a.tobytes() == b.tobytes()
            for a, b in zip(before_audio, after_audio)
        ),
    }
    if shapes_equal:
        # Conversion is for error arithmetic only, after inference has ended.
        delta = np.concatenate([
            a.astype(np.float64) - b.astype(np.float64)
            for a, b in zip(before_audio, after_audio)
        ])
        absolute = np.abs(delta)
        result.update({
            "max_abs_float_error": float(absolute.max()),
            "mean_abs_float_error": float(absolute.mean()),
            "float_rmse": float(np.sqrt(np.mean(delta * delta))),
            "different_float_samples": int(np.count_nonzero(delta)),
        })
    if len(before_pcm) == len(after_pcm):
        delta = (
            np.frombuffer(before_pcm, dtype="<i2").astype(np.int32)
            - np.frombuffer(after_pcm, dtype="<i2").astype(np.int32)
        )
        result.update({
            "different_pcm_samples": int(np.count_nonzero(delta)),
            "max_pcm_lsb_error": int(np.abs(delta).max()),
        })
    return result


def error_distribution(comparisons):
    result = {"n": len(comparisons)}
    for name in ("max_abs_float_error", "float_rmse",
                 "different_pcm_samples", "max_pcm_lsb_error"):
        values = [value[name] for value in comparisons if name in value]
        if values:
            result[name] = {"min": min(values),
                            "median": statistics.median(values),
                            "max": max(values)}
    return result


def run_native(args):
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "kind": "private decoder-only compile; complete development inputs",
        "model": MODEL, "voice": VOICE, "speed": 1.0,
        "snapshot": SNAPSHOT, "source_freeze": "c321634",
        "versions": {name: importlib.metadata.version(name)
                     for name in ("mlx-audio", "mlx", "misaki")},
        "compile": {
            "scope": "existing decoder only; original module retained",
            "shapeless": False,
            "captures": "original decoder array tree only",
            "rng_guard": "v2 exact next-draw public canary after inference",
            "cold_policy": "first compiled invocation of each complete text",
        },
        "controls": [], "cold": [], "pairs": [], "coverage": [],
        "numerical_distributions": [],
        "completed": False, "contract_passed": True,
        "strict_output_passed": True, "candidate_accepted": False,
    }

    def checkpoint():
        (output / "compiled-decoder.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )

    original = None
    model = None
    try:
        started = time.perf_counter()
        model = load_model(MODEL)
        report["load_seconds"] = time.perf_counter() - started
        if Path(model.config.model_path).name != SNAPSHOT:
            raise ValueError("Unexpected loaded Kokoro snapshot")
        original = model.decoder
        modules = list(model.named_modules())
        training = [name for name, module in modules if module.training]
        report["training_modules_before"] = training
        if training:
            raise ValueError("Loaded Kokoro must already be in evaluation mode")
        seen_compiled_shapes = set()

        def sample(case, seed, decoder):
            random.seed(seed)
            np.random.seed(seed)
            mx.random.seed(seed)
            calls = []

            def observed_decoder(*inputs):
                signature = tuple(
                    (tuple(value.shape), str(value.dtype)) for value in inputs
                )
                call = {"input_shapes_and_dtypes": signature}
                if decoder is not original:
                    call["first_compiled_shape_use"] = (
                        signature not in seen_compiled_shapes
                    )
                    seen_compiled_shapes.add(signature)
                calls.append(call)
                return decoder(*inputs)

            with owning_decoder(model, observed_decoder):
                result = native_sample(model, case.text, mx, np)
            result[0]["decoder_calls"] = calls
            result[0]["rng_next_draw"] = rng_canary(mx, np)
            result[0]["segment_audio_dtypes"] = [
                str(value.dtype) for value in result[2]
            ]
            return result

        warmup = sample(CASES[0], 231, original)
        report["baseline_warmup"] = warmup[0]
        started = time.perf_counter()
        compiled = mx.compile(
            original, inputs=original, shapeless=False,
        )
        report["compile_callable_creation_seconds"] = (
            time.perf_counter() - started
        )
        checkpoint()

        for case_index, case in enumerate(CASES):
            seed = 231000 + case_index * 100
            controls = [sample(case, seed, original)
                        for _ in range(args.controls)]
            control_errors = [
                compare_audio(before, after, np)
                for before, after in itertools.combinations(controls, 2)
            ]
            report["controls"].append({
                "case": case.name, "text": case.text,
                "samples": [value[0] for value in controls],
                "pairwise_errors": control_errors,
            })
            cold = sample(case, seed, compiled)
            cold_errors = compare_audio(controls[0], cold, np)
            cold_rng_equal = (
                controls[0][0]["rng_next_draw"]
                == cold[0]["rng_next_draw"]
            )
            report["contract_passed"] &= cold_rng_equal and all(
                cold_errors[key] for key in (
                    "same_shapes", "same_dtypes", "same_phoneme_counts",
                    "same_audio_duration",
                )
            )
            report["strict_output_passed"] &= (
                cold_errors["exact_pcm"] and cold_errors["exact_float_bytes"]
            )
            report["cold"].append({
                "case": case.name, "text": case.text,
                "record": cold[0],
                "vs_baseline": cold_errors,
                "same_rng_next_draw": cold_rng_equal,
            })
            checkpoint()
            if not cold_rng_equal:
                raise RuntimeError("Compiled cold call changed PRNG advancement")

            warm_errors = []
            for repeat in range(args.repeats):
                order = ("baseline", "compiled") if repeat % 2 == 0 else (
                    "compiled", "baseline"
                )
                values = {}
                for variant in order:
                    decoder = original if variant == "baseline" else compiled
                    values[variant] = sample(case, seed + repeat, decoder)
                baseline, candidate = values["baseline"], values["compiled"]
                errors = compare_audio(baseline, candidate, np)
                warm_errors.append(errors)
                rng_equal = (
                    baseline[0]["rng_next_draw"]
                    == candidate[0]["rng_next_draw"]
                )
                contract = rng_equal and all(errors[key] for key in (
                    "same_shapes", "same_dtypes", "same_phoneme_counts",
                    "same_audio_duration",
                ))
                strict = errors["exact_pcm"] and errors["exact_float_bytes"]
                report["contract_passed"] &= contract
                report["strict_output_passed"] &= strict
                report["pairs"].append({
                    "case": case.name, "text": case.text,
                    "text_chars": len(case.text), "repeat": repeat,
                    "seed": seed + repeat, "order": order,
                    "baseline": baseline[0], "compiled": candidate[0],
                    "errors": errors, "same_rng_next_draw": rng_equal,
                    "contract_passed": contract,
                })
                checkpoint()
                if not rng_equal:
                    raise RuntimeError("Compiled warm call changed PRNG advancement")

            report["numerical_distributions"].append({
                "case": case.name,
                "unchanged_baseline": error_distribution(control_errors),
                "compiled_warm": error_distribution(warm_errors),
                "compiled_cold_errors": cold_errors,
                "acceptance": "no tolerance; strict failures remain failures",
            })
            profiles = []
            for variant, decoder in (("baseline", original),
                                     ("compiled", compiled)):
                stages = Stages()
                with stages.collect(model, mx):
                    record, pcm, _ = sample(case, seed, decoder)
                full_text = compact(case.text) == compact(" ".join(
                    segment["graphemes"] for segment in stages.segments
                ))
                profiles.append({
                    "variant": variant, "record": record,
                    "complete_source_graphemes": full_text,
                    "segments": stages.segments,
                })
                report["contract_passed"] &= full_text
                if args.save_audio:
                    write_wav(output / f"{case.name}-{variant}.wav", pcm)
            phonemes_equal = [s["phonemes"] for s in profiles[0]["segments"]] == [
                s["phonemes"] for s in profiles[1]["segments"]
            ]
            report["coverage"].append({
                "case": case.name, "same_full_phonemes": phonemes_equal,
                "profiles": profiles,
            })
            report["contract_passed"] &= phonemes_equal
            report["peak_native_memory_bytes"] = mx.get_peak_memory()
            del controls, cold
            checkpoint()

        report["restored_baseline_check"] = sample(CASES[0], 231, original)[0]
        report["decoder_restored"] = model.decoder is original
        report["training_modules_after"] = [
            name for name, module in modules if module.training
        ]
        report["contract_passed"] &= (
            report["decoder_restored"]
            and report["training_modules_after"] == training
        )
        report["warm_timing_summary"] = {
            variant + "_first_pcm_mean": statistics.mean(
                pair[variant]["first_pcm_seconds"] for pair in report["pairs"]
            ) for variant in ("baseline", "compiled")
        }
        report["completed"] = True
        report["qualification_limit"] = (
            "No tolerance or observed-control range converts strict differences "
            "into a pass. Compare all raw errors with unchanged controls, "
            "then review complete saved speech before promotion. This is "
            "native synthetic development timing, not acoustic or benchmark QA."
        )
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        report["contract_passed"] = False
    finally:
        if model is not None and original is not None:
            model.decoder = original
            report["decoder_restored"] = model.decoder is original
        checkpoint()
    return 0 if (
        report["completed"] and report["contract_passed"]
        and report["strict_output_passed"]
    ) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "native", "_native"),
                        nargs="?", default="plan")
    parser.add_argument("--output", default=str(ROOT / "compiled-decoder-v1"))
    parser.add_argument("--repeats", type=int, choices=(2, 3), default=2)
    parser.add_argument("--controls", type=int, choices=(3, 4), default=3)
    parser.add_argument("--deadline", type=int, choices=range(30, 601), default=300)
    parser.add_argument("--save-audio", action="store_true")
    args = parser.parse_args()
    if args.mode == "plan":
        print(json.dumps({
            "mode": "plan only; no native imports, model loads or network",
            "candidate": "compile only existing owning-model decoder",
            "model": MODEL, "snapshot": SNAPSHOT, "voice": VOICE,
            "speed": 1.0, "dtype": "existing loaded dtype; no conversion",
            "source_freeze": "c321634", "bounded_seconds": args.deadline,
            "complete_texts": [{"case": case.name, "chars": len(case.text),
                                "text": case.text} for case in CASES],
            "generations": 2 + len(CASES) * (
                args.controls + 1 + args.repeats * 2 + 2
            ),
            "timing_pairs": len(CASES) * args.repeats,
            "unchanged_control_comparisons": len(CASES) * (
                args.controls * (args.controls - 1) // 2
            ),
            "first_text_compiled_calls": len(CASES),
            "cold_note": "actual first shape use is recorded; shapes may recur",
            "coverage_profiles": len(CASES) * 2,
            "quality_gate": "strict equality recorded; no arbitrary tolerance",
            "rng_guard": "public next-draw canary; abort on advancement mismatch",
            "native_authorization": "wait for root exclusive GPU slot",
        }, indent=2))
        return 0
    if args.mode == "_native":
        return run_native(args)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "_native",
               "--output", str(output), "--repeats", str(args.repeats),
               "--controls", str(args.controls)]
    if args.save_audio:
        command.append("--save-audio")
    environment = dict(os.environ, HF_HUB_OFFLINE="1",
                       HF_HUB_DISABLE_TELEMETRY="1")
    with (output / "compiled-decoder.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                 env=environment, start_new_session=True)
        try:
            return child.wait(timeout=args.deadline)
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
