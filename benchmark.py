"""Benchmark the Mac Pi voice agent. Run with the ME3 audio environment's Python."""
import argparse
import asyncio
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from statistics import mean, quantiles
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
PIN = "57eaddbc188ce9a19b8fd002b575f703426956f4"


def summarize(rows):
    return {"opportunities": sum(r["expected"] for r in rows),
            "hits": sum(r["expected"] and r["observed"] for r in rows),
            "quiet_windows": sum(not r["expected"] for r in rows),
            "false_alarms": sum(not r["expected"] and r["observed"] for r in rows)}


def personal_cases():
    from integrations.fdbench_pi import DigitalDevice
    from me3.incremental import is_acknowledgment
    from me3.parakeet_voice import Playback

    # Windows represent an incomplete SmartTurn decision after a pause.
    # Each group is an independent conversation. IDs and clocks within it persist.
    cases = [
        ("explaining", [("a", 0, 160, "I tried moving the sessions around and then", True),
                        ("a", 2, 250, "I tried another approach and then", False),
                        ("b", 6, 150, "I think the other option might be", False),
                        ("c", 15, 160, "I was also wondering whether we could", True)]),
        ("short hesitation", [("a", 0, 60, "what I mean is that we", False)]),
        ("giving a code", [("a", 0, 165, "the access code for this session is", False)]),
        ("question", [("a", 0, 180, "could we go over the latest changes?", False)]),
        ("story with place name", [("a", 0, 185, "after we arrived in Manila we started to", True)]),
        ("story with a time", [("a", 0, 180, "we left at 9 and after that we", True)]),
        ("verbatim quotation", [("a", 0, 180, "please write these words exactly as i say them", False)]),
    ]
    outgoing = []
    for label, windows in cases:
        device = DigitalDevice()
        player = Playback(device)
        player.allow_cue = True
        player.hold(True)
        for item, now, frames, text, expected in windows:
            with patch("me3.parakeet_voice.time.monotonic", return_value=100 + now), \
                    contextlib.redirect_stdout(io.StringIO()):
                player.acknowledge(SimpleNamespace(id=item, text=text, frames=frames))
            pcm = device.render(24000)
            outgoing.append(dict(case=label, turn=item, expected=expected,
                                 observed=any(pcm), nonzero_samples=sum(
                                     sample != 0 for sample in memoryview(pcm).cast("h"))))
    incoming = []
    for text, expected in [
        ("uh-huh", True), ("yeah", True), ("mm-hmm", True), ("I see", True),
        ("got it", True), ("yeah, change the date", False),
        ("okay stop reading", False), ("no, actually", False),
    ]:
        incoming.append(dict(case=text, expected=expected, observed=is_acknowledgment(text)))
    return {"evidence": "Scripted floor state and ASR text; actual Pi cue PCM and overlap classifier",
            "outgoing": {**summarize(outgoing), "cases": outgoing},
            "incoming": {**summarize(incoming), "cases": incoming}}


def recording_counts(run):
    timings = [
        json.loads(p.read_text()) for p in sorted(run.glob("trials/*/timing.json"))
        if p.with_name("her.flac").is_file() and p.with_name("played.flac").is_file()
    ]
    phrases = [t for t in timings if t.get("group") == "stage_latency"]
    overlaps = [t for t in timings if t.get("group") == "v15_backchannel"
                and t.get("variant") == "main"]
    return {
        "recording_count": len(timings),
        "phrase_trials_recorded": len(phrases),
        "phrase_recordings_with_agent_audio": sum(bool(t.get("bot_segments")) for t in phrases),
        "backchannel_trials_recorded": len(overlaps),
        "backchannel_overlaps_played": sum(bool(t.get("overlap_played")) for t in overlaps),
    }


def stage_answer_audio(run, sessions):
    """Match model-answer receipts to the class recording windows on this Mac."""
    starts, windows = {}, {}
    for line in (run / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        trial = event.get("trial")
        if event["event"] == "trial_start" and event["group"] == "stage_latency":
            starts[trial] = datetime.fromisoformat(event["t"]).timestamp()
        elif event["event"] == "trial_end" and trial in starts:
            # Upstream timestamps have whole-second precision.
            windows[trial] = (starts[trial], datetime.fromisoformat(event["t"]).timestamp() + 1)
    receipts = []
    for path in sessions.glob("session-*/*.jsonl"):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        answers = {e["id"] for e in events if e.get("event") == "answer"}
        for e in events:
            if e.get("event") == "first_output" and e["id"] in answers:
                at = datetime.fromisoformat(e["at"]).timestamp()
                receipts.append((at, e["vadEndToOutputMs"] / 1000))
    trials = {}
    for trial, (start, end) in windows.items():
        first = min((r for r in receipts if start <= r[0] < end), default=None)
        trials[trial] = first[1] if first else None
    times = [duration for duration in trials.values() if duration is not None]
    p95 = quantiles(times, n=100, method="inclusive")[94] if len(times) > 1 else next(iter(times), None)
    return {"with_answer_audio": len(times), "completed_stage_windows": len(windows),
            "mean_seconds": mean(times) if times else None, "p95_seconds": p95,
            "vad_end_to_answer_audio_seconds": trials}


def course(args, output, *, listening=False, overlap=False):
    bench = args.fdbench.resolve()
    py = bench / ".venv/bin/python"
    if not py.is_file():
        raise ValueError(f"Missing {py}. Install the pinned course checkout as in docs/SETUP.md.")
    version = subprocess.check_output(["git", "-C", bench, "rev-parse", "HEAD"], text=True).strip()
    if version != PIN or subprocess.run(
            ["git", "-C", bench, "diff", "--quiet", "HEAD", "--", "fdbench", "adapters"]).returncode:
        raise ValueError(f"Expected the unchanged course harness and adapters at {PIN}")
    env = dict(os.environ)
    if args.env_file.is_file():
        from dotenv import dotenv_values
        config = dotenv_values(args.env_file, interpolate=False)
        for key in ("OPENROUTER_API_KEY", "DEEPGRAM_API_KEY"):
            if config.get(key):
                env.setdefault(key, config[key])
    for key in ("OPENROUTER_API_KEY", "DEEPGRAM_API_KEY"):
        if not env.get(key):
            raise ValueError(f"Set {key} in the environment or --env-file.")
    from me3 import bmo
    model = Path(env.get("ME3_BMO_DIR", bmo.ROOT)).resolve()
    if not all(bmo.verify(model / name) for name in bmo.PINS):
        raise ValueError("BMO voice checksum mismatch. Run scripts/setup-bmo.sh.")
    env.update(
        ME3_FDBENCH_THINKING=args.thinking,
        FDBENCH_ASSISTANT_PYTHON=sys.executable,
        ME3_BMO_DIR=str(model),
        FDBENCH_MARKS=f"udp://127.0.0.1:{args.port + 1}",
        PYTHONPATH=os.pathsep.join((str(ROOT), str(bench / "adapters"))),
    )
    rounds, phrases, runs = args.rounds, args.phrases, args.runs
    suite = "class corpus"
    windows = None
    if listening:
        from integrations.listening_benchmark import make_clips
        windows = asyncio.run(make_clips(output / "stimuli", model))
        rounds, phrases, runs = 0, len(windows), 1
        suite = "custom listening audio"
        (output / "windows.json").write_text(json.dumps(windows, indent=2) + "\n")
    if overlap:
        phrases, runs = 0, 0
        suite = "class backchannel subset"
        collection = output / "dataset"
        collection.mkdir()
        source = bench / "datasets"
        manifest = json.loads((source / "manifest.json").read_text())
        manifest["groups"] = {"v15_backchannel": manifest["groups"]["v15_backchannel"]}
        (collection / "manifest.json").write_text(json.dumps(manifest))
        (collection / "v15_backchannel").symlink_to(source / "v15_backchannel", target_is_directory=True)
    python = sys.executable
    instance = "me3-pi-" + uuid.uuid4().hex[:12]
    controller = [python, str(ROOT / "integrations/benchmark_control.py")]
    with tempfile.TemporaryDirectory(prefix="me3bench-", dir="/tmp") as temp:
        shared = ["--control-dir", temp + "/ctrl", "--instance", instance]
        launch = [*controller, "serve", "--graceful", *shared, "--project", str(ROOT),
                  "--launcher", str(ROOT / "integrations/fdbench_pi_launcher.py"),
                  "--python", python, "--log-root", str(output / "sessions"),
                  "--url", f"ws://127.0.0.1:{args.port}"]
        cmd = [str(py), "-m", "fdbench", "run", "--student", instance, "--seed", "231",
               "--rounds", str(rounds),
               "--phrases", str(phrases),
               "--runs", str(runs),
               "--port", str(args.port), "--marks-port", str(args.port+1),
               "--connect", "direct", "--where", "local", "--project", str(ROOT),
               "--assistant-cmd", shlex.join(launch), "--reset-cmd", shlex.join([*controller, "reset", *shared]),
               "--judge-provider", "none", "--yes", "--no-score"]
        if overlap:
            cmd.extend(["--datasets", str(collection)])
        if windows:
            cmd.extend(["--phrases-dir", str(output / "stimuli")])
        try:
            subprocess.run(cmd, cwd=bench, env=env, check=True)
        finally:
            if (Path(temp) / "ctrl/control.sock").exists():
                subprocess.run([*controller, "stop", *shared], stdout=subprocess.DEVNULL)
    run, = (bench / "runs" / instance).iterdir()
    print(f"Official recordings and results: {run}", flush=True)
    subprocess.run([str(py), "-m", "fdbench", "score", str(run), "--judge-provider", "none",
                    "--no-utmos", "--asr-model", "small"], cwd=bench, env=env, check=True)
    session = json.loads((run / "session.json").read_text())
    result = {"suite": suite, **recording_counts(run),
              "scheduled_phrase_trials": session["stage_test"]["phrases"] * session["stage_test"]["runs"],
              "pin": version, "thinking": args.thinking, "recordings": str(run), "outcome": session["outcome"],
              "group_counts": session["dataset_counts"], "profile": "Pi.dev / Deepgram Nova-3 / DeepSeek V4.1 Flash Nitro / BMO Piper",
              "voice_sha256": bmo.PINS["bmo.onnx"]}
    result["stage_answer_audio"] = stage_answer_audio(run, output / "sessions")
    (output / "course.json").write_text(json.dumps(result, indent=2) + "\n")
    if windows:
        from integrations.listening_benchmark import score_windows
        rows = score_windows(run, windows, model)
        metrics = summarize([row for row in rows if row["status"] == "measured"])
        report = dict(metrics, missing=sum(r["observed"] is None for r in rows), cases=rows)
        (output / "listening-audio.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Recorded assistant cues:", metrics, "missing:", report["missing"])
    for timing in run.glob("trials/*/timing.json"):
        if json.loads(timing.read_text()).get("score_error"):
            raise ValueError(f"Class scorer error in {timing}")
    if listening and (report["missing"] or metrics["hits"] != metrics["opportunities"] or metrics["false_alarms"]):
        raise ValueError("Listening checks failed. See listening-audio.json.")
    if session["outcome"]["completed"] != session["outcome"]["total"]:
        raise ValueError("Course queue incomplete. See course.json and the recordings.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite", nargs="?", choices=["all", "course", "cues", "listening", "overlap", "routing", "spoken-routing"], default="all")
    p.add_argument("--fdbench", type=Path, default=ROOT / ".local/fd-benchmark-20261107")
    p.add_argument("--env-file", type=Path, default=ROOT / ".local/benchmark.env")
    p.add_argument("--output", type=Path, help="new report directory, defaults under .local/benchmarks/")
    p.add_argument("--port", type=int, default=18391, help="two adjacent loopback ports for course audio and marks")
    p.add_argument("--thinking", choices=["off", "low"], default="off",
                   help="off matches the current Pi launcher; low is a separate provider comparison")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--phrases", type=int, default=10)
    p.add_argument("--runs", type=int, default=3)
    a = p.parse_args()
    if not 1 <= a.port < 65535 or min(a.rounds, a.phrases, a.runs) < 0:
        p.error("Invalid port or negative trial count")
    if a.suite in ("all", "course") and not (a.rounds or a.phrases * a.runs):
        p.error("Select at least one course trial")
    out = (a.output or ROOT / ".local/benchmarks" / uuid.uuid4().hex[:12]).resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    print(f"ME3 benchmark report: {out}", flush=True)
    errors = []
    if a.suite in ("all", "cues"):
        with patch.dict(os.environ, ME3_VOICE_TTS="bmo"):
            report = personal_cases()
        (out / "cues.json").write_text(json.dumps(report, indent=2) + "\n")
        for direction in ("outgoing", "incoming"):
            metrics = summarize(report[direction]["cases"])
            print(direction, metrics, flush=True)
            if metrics["hits"] != metrics["opportunities"] or metrics["false_alarms"]:
                errors.append(f"{direction} cue checks failed")
    if a.suite == "overlap" and not a.rounds:
        p.error("overlap requires at least one round")
    live_suites = ["course", "listening", "routing", "spoken-routing"] if a.suite == "all" else [a.suite]
    for suite in live_suites:
        if suite == "cues":
            continue
        folder = out / suite if a.suite == "all" else out
        folder.mkdir(mode=0o700, exist_ok=True)
        try:
            if suite == "spoken-routing":
                from integrations.pi_routing_benchmark import evaluate
                bench = a.fdbench.resolve()
                sys.path.insert(0, str(bench))
                from fdbench.rig.direct import DirectRig
                # The upstream socket handler suppresses playback-resampler errors.
                # Exercise it before starting a paid session or accepting any audio.
                import numpy as np
                from fdbench.util import resample
                try:
                    resample(np.zeros(480, dtype=np.float32), 24000, 16000)
                except ImportError as exc:
                    raise ValueError("Install the benchmark audio dependencies with "
                                     "python -m pip install -e '.[benchmark-audio]'") from exc
                rig = DirectRig(port=a.port)
                rig.open()
                try:
                    asyncio.run(evaluate(ROOT, folder, a.env_file, a.thinking, rig=rig, fdbench=bench))
                finally:
                    rig.close()
                continue
            if suite == "routing":
                from integrations.pi_routing_benchmark import evaluate
                asyncio.run(evaluate(ROOT, folder, a.env_file, a.thinking))
                continue
            course(a, folder, listening=suite == "listening", overlap=suite == "overlap")
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            errors.append(f"{suite}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
