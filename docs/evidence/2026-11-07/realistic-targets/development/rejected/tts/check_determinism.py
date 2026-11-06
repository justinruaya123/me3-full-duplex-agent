"""Same-baseline controls; explicit native run with a 120-second deadline."""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from profile_tts import CASES, MODEL, ROOT, native_sample


def run(output):
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model

    model = load_model(MODEL)
    training = [name for name, module in model.named_modules() if module.training]
    native_sample(model, "The instruments are ready.", mx, np)
    report = {"kind": "same-baseline native controls; all RNGs reset; loader eval state unchanged", "training_modules_before": training, "trials": [], "rng_profiles": []}

    def seed():
        random.seed(231)
        np.random.seed(231)
        mx.random.seed(231)

    for case in CASES:
        values = []
        for repeat in range(2):
            seed()
            record, pcm, audio = native_sample(model, case.text, mx, np)
            values.append((record, pcm, audio))
        before, after = values
        arrays_match = len(before[2]) == len(after[2]) and all(a.shape == b.shape for a, b in zip(before[2], after[2]))
        deltas = [np.abs(a - b).astype(np.float64) for a, b in zip(before[2], after[2])] if arrays_match else []
        report["trials"].append({"case": case.name, "before": before[0], "after": after[0], "exact_pcm": before[1] == after[1], "same_shapes": arrays_match, "max_abs_float_difference": max(float(a.max()) for a in deltas) if deltas else None, "rmse": float(np.sqrt(np.concatenate(deltas).dot(np.concatenate(deltas)) / sum(a.size for a in deltas))) if deltas else None})
        (output / "determinism.json").write_text(json.dumps(report, indent=2) + "\n")

    # Separate instrumented check of the actual excitation RNG draws.
    original_uniform, original_normal = mx.random.uniform, mx.random.normal
    for repeat in range(2):
        draws = []

        def capture(name, function):
            def measured(*args, **kwargs):
                result = function(*args, **kwargs)
                data = np.asarray(result)
                draws.append({"name": name, "shape": list(data.shape), "sha256": hashlib.sha256(data.tobytes()).hexdigest()})
                return result
            return measured

        seed()
        with patch.object(mx.random, "uniform", capture("uniform", original_uniform)), patch.object(mx.random, "normal", capture("normal", original_normal)):
            record, _, _ = native_sample(model, CASES[0].text, mx, np)
        report["rng_profiles"].append({"repeat": repeat, "record": record, "draws": draws})
    report["training_modules_after"] = [name for name, module in model.named_modules() if module.training]
    report["all_rng_draws_identical"] = report["rng_profiles"][0]["draws"] == report["rng_profiles"][1]["draws"]
    report["exact_pcm_controls"] = sum(trial["exact_pcm"] for trial in report["trials"])
    (output / "determinism.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    output = ROOT / "native-v1"
    if args.child:
        run(output)
        return 0
    with (output / "determinism.log").open("w") as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child"], stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, HF_HUB_OFFLINE="1"))
        try:
            return child.wait(timeout=120)
        except BaseException:
            child.kill()
            child.wait()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
