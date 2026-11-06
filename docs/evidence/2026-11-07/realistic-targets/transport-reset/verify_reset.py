"""Actual fdbench handler/launcher/ME3 initialization; never send input audio.

Run with the benchmark venv from its checkout via runpy, after sourcing the
operator environment and setting the explicit FDBENCH_* paths. This omits the
DirectRig clock because that clock would feed silence without an active trial.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid


def write_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")


def command(argv, *, cwd, timeout=5, env=None):
    return subprocess.run(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True, text=True, timeout=timeout,
    ).stdout.strip()


def wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise TimeoutError("transport verification condition did not become true")


def exists(pid, *, group=False):
    try:
        (os.killpg if group else os.kill)(pid, 0)
        return True
    except ProcessLookupError:
        return False


def source_pin(project, bench):
    relevant = [
        "me3/capture.py", "me3/audio_pipeline.py", "me3/runtime.py",
        "me3/duplex.py", "me3/core.py", "me3/jobs.py", "me3/ownership.py",
        "me3/foreground.py", "me3/speech.py", "me3/configuration.py",
        "me3/harnesses.py", "integrations/fdbench_entry.py",
        "integrations/benchmark_control.py",
    ]
    external = [bench / "launch_assistant.py",
                bench / "adapters/pipecat_fdbench.py",
                bench / "fdbench/rig/direct.py"]
    external.extend(sorted((bench / "fdbench/score").glob("*.py")))
    paths = [("project/" + name, project / name) for name in relevant]
    paths.extend(("benchmark/" + str(path.relative_to(bench)), path)
                 for path in external)
    return {
        "project_commit": command(["git", "rev-parse", "HEAD"], cwd=project),
        "benchmark_commit": command(["git", "rev-parse", "HEAD"], cwd=bench),
        "benchmark_status": command(
            ["git", "status", "--porcelain"], cwd=bench,
        ),
        "sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for name, path in paths},
    }


def inspect_runtime(state):
    directories = sorted(Path(state["log_dir"]).glob("runtime-*"))
    if len(directories) != 1:
        raise RuntimeError("expected exactly one actual ME3 runtime")
    root = directories[0]
    with sqlite3.connect(f"file:{root / 'jobs.sqlite3'}?mode=ro", uri=True) as db:
        jobs = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    events = [json.loads(line)["event"]
              for line in (root / "events.jsonl").read_text().splitlines()]
    return {"path": str(root), "job_rows": jobs,
            "event_counts": dict(Counter(events))}


def main():
    from fdbench.rig.direct import DirectRig
    from websockets.sync.server import serve

    project = Path(os.environ["FDBENCH_PROJECT"])
    bench = project / ".local/fd-benchmark-20261107"
    python = Path(os.environ["FDBENCH_ASSISTANT_PYTHON"])
    entry = Path(os.environ["FDBENCH_ENTRY"])
    if (entry != project / "integrations/fdbench_entry.py"
            or os.environ["ME3_BENCHMARK_PROFILE"] != "course"):
        raise RuntimeError("explicit benchmark paths/profile do not match")
    evidence = Path(__file__).resolve().parent
    evidence.chmod(0o700)
    (evidence / "guard").chmod(0o700)
    run_id = uuid.uuid4().hex
    run_dir = evidence / (datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ-",
    ) + run_id[:8])
    run_dir.mkdir(mode=0o700)
    audit_dir = run_dir / "audit"
    audit_dir.mkdir(mode=0o700)
    control_dir = Path("/tmp") / ("me3rt-" + run_id)
    script = project / "integrations/benchmark_control.py"
    launcher = bench / "launch_assistant.py"
    result = {
        "kind": "actual unchanged WS handler/launcher/ME3 initialization reset",
        "not_qualified": ["full benchmark", "ASR/TTS/LLM/worker inference",
                          "provider smoke", "acoustic capture", "hardware"],
        "conditions": {
            "direct_rig_clock_omitted": True, "input_audio_fed": False,
            "cpu_onnx_initialization": True,
            "child_tcp_restricted_to_owned_ws_port": True,
            "websocket_close_timeout_seconds": 2,
        },
        "paths": {"FDBENCH_PROJECT": str(project),
                  "FDBENCH_ENTRY": str(entry),
                  "FDBENCH_ASSISTANT_PYTHON": str(python)},
        "profile": "course", "verification_python": sys.version,
        "source_before": source_pin(project, bench),
    }
    if result["source_before"]["benchmark_status"]:
        raise RuntimeError("external benchmark was not clean before checking")
    counts = Counter()
    stages = Counter()
    observations = []
    lock = threading.Lock()
    rig = DirectRig(host="127.0.0.1", port=0)

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __iter__(self):
            for message in self.connection:
                with lock:
                    if isinstance(message, bytes):
                        counts["assistant_binary_frames"] += 1
                        counts["assistant_binary_bytes"] += len(message)
                    else:
                        event = json.loads(message)
                        counts["assistant_text:" + event.get("event", "?")] += 1
                        if event.get("event") == "mark":
                            stages[event.get("stage", "?")] += 1
                yield message

        def send(self, message):
            with lock:
                counts["server_send_calls"] += 1
                if isinstance(message, bytes):
                    counts["server_binary_frames"] += 1
                    counts["server_binary_bytes"] += len(message)
            return self.connection.send(message)

    def handle(connection):
        with lock:
            observations.append({"peer": list(connection.remote_address),
                                 "connected_mono": time.monotonic()})
        rig._handler(ObservedConnection(connection))

    # Same upstream WS handler/server settings; no clock, run(), or audio send.
    server = serve(handle, "127.0.0.1", 0, max_size=None,
                   compression=None, ping_interval=None, close_timeout=2)
    rig._server = server
    rig.port = server.socket.getsockname()[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(evidence / "guard") + (
        os.pathsep + prior if prior else ""
    )
    env["ME3_RESET_AUDIT_DIR"] = str(audit_dir)
    env["ME3_RESET_WS_PORT"] = str(rig.port)
    assistant = [str(python), str(script), "serve", "--control-dir",
                 str(control_dir), "--instance", run_id, "--project",
                 str(project), "--launcher", str(launcher), "--url", rig.url,
                 "--log-root", str(run_dir / "sessions")]
    reset = [str(python), str(script), "reset", "--control-dir",
             str(control_dir), "--instance", run_id]
    result["assistant_command"] = shlex.join(assistant)
    result["reset_command"] = shlex.join(reset)
    owned_children = set()
    wrapper = None
    output = os.fdopen(os.open(run_dir / "wrapper.log",
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
    closer = None
    try:
        started = time.monotonic()
        wrapper = subprocess.Popen(
            shlex.split(result["assistant_command"]), cwd=project, env=env,
            stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

        def ready():
            if wrapper.poll() is not None:
                raise RuntimeError("wrapper exited before initial connection")
            path = control_dir / "state.json"
            if not path.exists():
                return None
            state = json.loads(path.read_text())
            if state.get("pid"):
                owned_children.add(state["pid"])
            return state if state.get("ready") else None

        first = wait_for(ready, 45)
        result["initial_start_seconds"] = time.monotonic() - started
        if not rig.connected.is_set():
            raise RuntimeError("wrapper readiness preceded actual WS connection")
        first_runtime = inspect_runtime(first)
        result["first"] = {"control": first, "runtime": first_runtime,
                           "ping_rtt_ms": rig.measure_rtt(1),
                           "process_group": os.getpgid(first["pid"])}
        started = time.monotonic()
        # Match the upstream --reset-cmd shell invocation, with quoted argv.
        reset_process = subprocess.run(
            result["reset_command"], shell=True, cwd=bench, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=58, check=True,
        )
        second = json.loads(reset_process.stdout)
        owned_children.add(second["pid"])
        result["reset_seconds"] = time.monotonic() - started
        wait_for(lambda: len(observations) == 2, 3)
        second_runtime = inspect_runtime(second)
        result["second"] = {"control": second, "runtime": second_runtime,
                            "ping_rtt_ms": rig.measure_rtt(1),
                            "process_group": os.getpgid(second["pid"])}
        result["old_pid_exists_after_reset"] = exists(first["pid"])
        result["old_group_exists_after_reset"] = exists(
            first["pid"], group=True,
        )
        if (first["pid"] == second["pid"] or first["generation"] != 1
                or second["generation"] != 2
                or first_runtime["path"] == second_runtime["path"]
                or result["old_pid_exists_after_reset"]
                or result["old_group_exists_after_reset"]):
            raise RuntimeError("reset did not replace the complete owned lifetime")
        time.sleep(0.2)
        started = time.monotonic()
        closer = threading.Thread(target=rig.close, daemon=True)
        closer.start()
        result["wrapper_returncode"] = wrapper.wait(timeout=12)
        closer.join(timeout=3)
        server_thread.join(timeout=3)
        result["normal_disconnect_cleanup_seconds"] = time.monotonic() - started
        result["close_thread_stopped"] = not closer.is_alive()
        result["server_thread_stopped"] = not server_thread.is_alive()
        result["new_pid_exists_after_disconnect"] = exists(second["pid"])
        result["new_group_exists_after_disconnect"] = exists(
            second["pid"], group=True,
        )
        result["control_socket_removed"] = not (
            control_dir / "control.sock"
        ).exists()
        result["disconnects"] = rig.disconnects
        with lock:
            result["wire_counts"] = dict(counts)
            result["stages"] = dict(stages)
            result["connections"] = list(observations)
        for state in (first, second):
            audit_path = audit_dir / f"{state['pid']}.jsonl"
            events = [json.loads(line)
                      for line in audit_path.read_text().splitlines()]
            if not any(item["event"] == "guard_installed" for item in events):
                raise RuntimeError("launcher audit guard did not initialize")
            if any(item["event"] == "tcp_connect" and not item["allowed"]
                   for item in events):
                raise RuntimeError("a forbidden provider connection was attempted")
        result["audit"] = {
            path.stem: [json.loads(line)
                        for line in path.read_text().splitlines()]
            for path in sorted(audit_dir.glob("*.jsonl"))
        }
        result["runtime_after_disconnect"] = [inspect_runtime(first),
                                               inspect_runtime(second)]
        for runtime in result["runtime_after_disconnect"]:
            if runtime["job_rows"] or any(
                event.startswith(("transcript", "foreground", "speech_submitted"))
                for event in runtime["event_counts"]
            ):
                raise RuntimeError("unexpected inference/job runtime activity")
        inference_stages = {
            "vad_start", "vad_end", "asr_partial", "asr_final", "llm_request",
            "llm_first_token", "tts_request", "tts_first_audio", "audio_out",
            "tool_start", "tool_end",
        }
        if (counts["server_binary_frames"] or counts["assistant_binary_frames"]
                or inference_stages.intersection(stages)
                or result["wrapper_returncode"] != 0
                or result["new_pid_exists_after_disconnect"]
                or result["new_group_exists_after_disconnect"]
                or not result["close_thread_stopped"]
                or not result["server_thread_stopped"]
                or not result["control_socket_removed"]):
            raise RuntimeError("wire or shutdown boundary failed")
        result["source_after"] = source_pin(project, bench)
        if (result["source_before"]["sha256"]
                != result["source_after"]["sha256"]
                or result["source_after"]["benchmark_status"]):
            raise RuntimeError("source pins changed during verification")
        result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if wrapper is not None and wrapper.poll() is None:
            wrapper.terminate()
            try:
                wrapper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                wrapper.kill()
                wrapper.wait(timeout=2)
        state_path = control_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state.get("pid"):
                owned_children.add(state["pid"])
        # Explicit emergency cleanup for this verification's recorded children.
        for pid in owned_children:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if closer is None:
            closer = threading.Thread(target=rig.close, daemon=True)
            closer.start()
        closer.join(timeout=4)
        server_thread.join(timeout=2)
        output.close()
        write_json(run_dir / "result.json", result)
        print(json.dumps({"passed": result.get("passed", False),
                          "result": str(run_dir / "result.json")}))


if __name__ == "__main__":
    main()
