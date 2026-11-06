"""Local control/transport fixtures; no models, provider, or audio devices."""

import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from integrations.benchmark_control import ControlError, request

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "integrations" / "benchmark_control.py"
INSTANCE = "fixture-benchmark-instance"
FIXTURE = '''import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

p = argparse.ArgumentParser()
p.add_argument("--url")
p.add_argument("--project")
p.add_argument("--once", action="store_true")
p.add_argument("--wait")
p.add_argument("--log-dir", type=Path)
a = p.parse_args()
mode = os.environ.get("FIXTURE_MODE", "ready")
a.log_dir.mkdir(exist_ok=True)
(a.log_dir / "fixture.json").write_text(json.dumps({
    "pid": os.getpid(), "once": a.once, "url": a.url,
    "project": a.project, "log_dir": str(a.log_dir),
}))
if mode == "fail-reset" and "000002" in a.log_dir.name:
    sys.exit(7)
if mode == "descendant":
    code = ("import signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code])
    (a.log_dir / "descendant.pid").write_text(str(child.pid))
    time.sleep(0.05)
if mode == "no-ready":
    time.sleep(60)
    sys.exit(0)
conn = None
if os.environ.get("FIXTURE_CONNECT") == "1":
    url = urlparse(a.url)
    conn = socket.create_connection((url.hostname, url.port))
    conn.sendall(str(os.getpid()).encode() + b"\\n")
print(f"connected to fdbench at {a.url} · benchmark mode", flush=True)
if conn is not None:
    while conn.recv(1024):
        pass
    print("fdbench closed the connection: run over, "
          "shutting the assistant down", flush=True)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(60)
'''


def wait_until(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("fixture condition did not become true")


def is_running(pid):
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
        text=True, check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


class BenchmarkControlTests(unittest.TestCase):
    def setUp(self):
        # Keep AF_UNIX paths below macOS's 104-byte sockaddr limit.
        self.temp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.control = self.root / "control"
        self.logs = self.root / "logs"
        self.fixture = self.root / "launch_fixture.py"
        self.fixture.write_text(FIXTURE, encoding="utf-8")
        self.processes = []
        self.addCleanup(self.stop_wrappers)

    def stop_wrappers(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def launch(self, *, mode="ready", url="ws://127.0.0.1:8791",
               connect=False, start_timeout=2.0):
        output = open(self.root / "wrapper.log", "ab")
        self.addCleanup(output.close)
        env = dict(os.environ, FIXTURE_MODE=mode)
        if connect:
            env["FIXTURE_CONNECT"] = "1"
        process = subprocess.Popen(
            [sys.executable, str(CONTROL), "serve", "--control-dir",
             str(self.control), "--instance", INSTANCE, "--launcher",
             str(self.fixture), "--project", str(self.root), "--python",
             sys.executable, "--url", url, "--log-root", str(self.logs),
             "--start-timeout", str(start_timeout), "--stop-timeout", "0.2"],
            stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, env=env,
        )
        self.processes.append(process)
        return process

    def ready(self):
        def read():
            try:
                return request(self.control, INSTANCE, "status", timeout=0.2)
            except (ControlError, FileNotFoundError, OSError):
                return None
        return wait_until(read)

    def raw_request(self, payload):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(self.control / "control.sock"))
            encoded = (payload if isinstance(payload, bytes)
                       else json.dumps(payload).encode())
            client.sendall(encoded + b"\n")
            return json.loads(client.recv(4096))

    def test_reset_reconnects_new_child_with_fresh_log_and_runtime_tree(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(2)
            listener.settimeout(3)
            url = f"ws://127.0.0.1:{listener.getsockname()[1]}"
            process = self.launch(url=url, connect=True)
            before = self.ready()
            old_conn, _ = listener.accept()
            self.addCleanup(old_conn.close)
            self.assertEqual(int(old_conn.recv(64)), before["pid"])
            old_dir = Path(before["log_dir"])
            (old_dir / "runtime-stale").write_text("old context")
            after = request(self.control, INSTANCE, "reset", timeout=3)
            new_conn, _ = listener.accept()
            self.addCleanup(new_conn.close)
            self.assertEqual(int(new_conn.recv(64)), after["pid"])
            old_conn.settimeout(1)
            self.assertEqual(old_conn.recv(1), b"")
            self.assertNotEqual(before["pid"], after["pid"])
            self.assertEqual((before["generation"], after["generation"]),
                             (1, 2))
            self.assertNotEqual(before["log_dir"], after["log_dir"])
            stale = Path(after["log_dir"]) / "runtime-stale"
            self.assertFalse(stale.exists())
            fixture = json.loads(
                (Path(after["log_dir"]) / "fixture.json").read_text(),
            )
            self.assertTrue(fixture["once"])
            self.assertEqual(fixture["url"], url)
            self.assertFalse(is_running(before["pid"]))
            self.assertIsNone(process.poll())

    def test_wrong_instance_and_replayed_generation_cannot_reset(self):
        self.launch()
        before = self.ready()
        after = request(self.control, INSTANCE, "reset", timeout=3)
        for instance, generation in (("another-instance", 2), (INSTANCE, 1)):
            result = self.raw_request({
                "instance": instance, "generation": generation, "op": "reset",
            })
            self.assertFalse(result["ok"])
        current = request(self.control, INSTANCE, "status", timeout=1)
        self.assertEqual(current["pid"], after["pid"])
        self.assertEqual(current["generation"], before["generation"] + 1)

    def test_control_rejects_insecure_or_symlink_directory(self):
        self.launch()
        self.ready()
        self.assertEqual(self.control.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.control / "control.sock").stat().st_mode
                         & 0o777, 0o600)
        self.control.chmod(0o755)
        try:
            with self.assertRaises(ControlError):
                request(self.control, INSTANCE, "reset", timeout=1)
        finally:
            self.control.chmod(0o700)
        link = self.root / "link"
        link.symlink_to(self.control, target_is_directory=True)
        with self.assertRaises(ControlError):
            request(link, INSTANCE, "reset", timeout=1)

    def test_existing_control_directory_is_preserved_and_refused(self):
        self.control.mkdir(mode=0o700)
        marker = self.control / "keep"
        marker.write_text("previous instance")
        process = self.launch()
        self.assertNotEqual(process.wait(timeout=3), 0)
        self.assertEqual(marker.read_text(), "previous instance")
        self.assertFalse((self.control / "control.sock").exists())

    def test_reset_kills_descendant_even_after_launcher_exits_on_term(self):
        self.launch(mode="descendant")
        before = self.ready()
        descendant = int(
            (Path(before["log_dir"]) / "descendant.pid").read_text(),
        )
        self.assertTrue(is_running(descendant))
        request(self.control, INSTANCE, "reset", timeout=3)
        wait_until(lambda: not is_running(descendant))
        self.assertFalse(is_running(before["pid"]))

    def test_start_timeout_reaps_child_and_removes_socket(self):
        process = self.launch(mode="no-ready", start_timeout=0.15)
        fixture_path = self.logs / "session-000001" / "fixture.json"
        wait_until(fixture_path.exists)
        pid = json.loads(fixture_path.read_text())["pid"]
        self.assertNotEqual(process.wait(timeout=3), 0)
        self.assertFalse(is_running(pid))
        self.assertFalse((self.control / "control.sock").exists())

    def test_failed_reset_is_terminal_without_old_session_fallback(self):
        process = self.launch(mode="fail-reset")
        before = self.ready()
        with self.assertRaises(ControlError):
            request(self.control, INSTANCE, "reset", timeout=3)
        self.assertNotEqual(process.wait(timeout=3), 0)
        self.assertFalse(is_running(before["pid"]))
        self.assertFalse((self.control / "control.sock").exists())

    def test_disconnect_bounds_hung_cleanup_below_upstream_wait(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            url = f"ws://127.0.0.1:{listener.getsockname()[1]}"
            process = self.launch(url=url, connect=True)
            state = self.ready()
            conn, _ = listener.accept()
            conn.recv(64)
            started = time.monotonic()
            conn.close()
            self.assertEqual(process.wait(timeout=3), 0)
            self.assertLess(time.monotonic() - started, 3)
            self.assertFalse(is_running(state["pid"]))
            self.assertFalse((self.control / "control.sock").exists())

    def test_term_and_explicit_stop_reap_owned_child(self):
        for use_signal in (True, False):
            with self.subTest(signal=use_signal):
                # Each invocation owns a new exclusive control/log directory.
                self.control = self.root / ("signal" if use_signal else "stop")
                self.logs = self.root / ("signal-logs" if use_signal
                                         else "stop-logs")
                process = self.launch()
                state = self.ready()
                if use_signal:
                    process.send_signal(signal.SIGTERM)
                else:
                    request(self.control, INSTANCE, "stop", timeout=3)
                self.assertEqual(process.wait(timeout=3), 0)
                self.assertFalse(is_running(state["pid"]))
                self.assertFalse((self.control / "control.sock").exists())

    def test_malformed_or_stalled_request_cannot_block_control(self):
        self.launch()
        before = self.ready()
        result = self.raw_request({"instance": INSTANCE, "op": "shell"})
        self.assertFalse(result["ok"])
        with socket.socket(socket.AF_UNIX) as stalled:
            stalled.connect(str(self.control / "control.sock"))
            started = time.monotonic()
            after = request(self.control, INSTANCE, "status", timeout=2)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(before["pid"], after["pid"])

    def test_invalid_operation_type_cannot_terminate_control_parent(self):
        self.launch()
        before = self.ready()
        for operation in ([], {}, None, True, 7):
            result = self.raw_request({
                "instance": INSTANCE, "generation": before["generation"],
                "op": operation,
            })
            self.assertFalse(result["ok"])
        after = request(self.control, INSTANCE, "status", timeout=1)
        self.assertEqual(before["pid"], after["pid"])

    def test_invalid_state_fifo_cannot_block_control_client(self):
        self.launch()
        before = self.ready()
        state = self.control / "state.json"
        saved = state.read_bytes()
        state.unlink()
        os.mkfifo(state, mode=0o600)
        try:
            result = subprocess.run(
                [sys.executable, str(CONTROL), "status", "--control-dir",
                 str(self.control), "--instance", INSTANCE,
                 "--timeout", "0.2"],
                capture_output=True, timeout=1, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
        finally:
            state.unlink()
            state.write_bytes(saved)
            state.chmod(0o600)
        after = request(self.control, INSTANCE, "status", timeout=1)
        self.assertEqual(before["pid"], after["pid"])

    def test_invalid_timeout_is_rejected_before_connecting(self):
        for timeout in (0, -1, math.nan, math.inf, -math.inf, 56):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ControlError, "timeout"):
                    request(self.control, INSTANCE, "status", timeout=timeout)

    def test_invalid_and_oversized_messages_cannot_reset(self):
        self.launch()
        before = self.ready()
        oversized = json.dumps({
            "instance": INSTANCE, "generation": before["generation"],
            "op": "reset", "padding": "x" * 5000,
        }).encode()
        for payload in (b"not-json", oversized):
            self.assertFalse(self.raw_request(payload)["ok"])
        after = request(self.control, INSTANCE, "status", timeout=1)
        self.assertEqual(before["pid"], after["pid"])

    def test_slow_trickle_cannot_extend_request_deadline(self):
        self.launch()
        before = self.ready()
        with socket.socket(socket.AF_UNIX) as stalled:
            stalled.connect(str(self.control / "control.sock"))

            def trickle():
                for _ in range(15):
                    try:
                        stalled.sendall(b" ")
                    except OSError:
                        return
                    time.sleep(0.1)

            writer = threading.Thread(target=trickle)
            writer.start()
            try:
                started = time.monotonic()
                after = request(self.control, INSTANCE, "status", timeout=1)
                self.assertLess(time.monotonic() - started, 0.9)
                self.assertEqual(before["pid"], after["pid"])
            finally:
                stalled.close()
                writer.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
