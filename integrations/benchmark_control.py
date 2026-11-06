"""Explicit local fdbench process resets; never a normal voice-session control.

Run ``serve`` as fdbench's --assistant-cmd and ``reset`` as --reset-cmd.
Each accepted reset destroys the owned launcher's process group, then starts
the unchanged launch_assistant.py --once with a new log/runtime directory.
No trial labels, corpus metadata, expected answers, or judge output are read.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

MAX_MESSAGE = 4096
SOCKET_NAME = "control.sock"
STATE_NAME = "state.json"
DISCONNECTED = (
    b"fdbench closed the connection: run over, shutting the assistant down"
)


class ControlError(RuntimeError):
    """The explicitly selected benchmark control operation did not succeed."""


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ControlError(
            "control directory must be owned, private, and real",
        )


def _read_message(connection: socket.socket, deadline: float) -> dict:
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ControlError("control message deadline expired")
        connection.settimeout(remaining)
        chunk = connection.recv(min(1024, MAX_MESSAGE + 1 - len(data)))
        if not chunk:
            raise ControlError("incomplete control message")
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise ControlError("control message exceeds limit")
    try:
        value = json.loads(data.split(b"\n", 1)[0])
    except (ValueError, UnicodeError) as exc:
        raise ControlError("invalid control JSON") from exc
    if not isinstance(value, dict):
        raise ControlError("control message must be an object")
    return value


def request(control_dir: Path, instance: str, operation: str, *,
            timeout: float = 55.0) -> dict:
    """Request one operation for the current generation of a private wrapper.

    Directory/socket ownership is the local authorization boundary. The
    instance and generation fence old invocations and concurrent reset replays.
    A run must use a new, exclusive control directory, even after shutdown.
    """
    if not math.isfinite(timeout) or not 0 < timeout <= 55:
        raise ControlError(
            "control timeout must be finite and 0 < timeout <= 55",
        )
    control_dir = Path(control_dir)
    _private_directory(control_dir)
    path = control_dir / STATE_NAME
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as state:
        info = os.fstat(state.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ControlError("control state must be owned and private")
        try:
            current = json.loads(state.read(MAX_MESSAGE + 1))
        except (ValueError, UnicodeError) as exc:
            raise ControlError("invalid control state") from exc
    if not isinstance(current, dict) or current.get("instance") != instance:
        raise ControlError("benchmark wrapper instance does not match")
    endpoint = control_dir / SOCKET_NAME
    info = endpoint.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise ControlError("control socket must be owned and private")
    payload = {"instance": instance, "generation": current.get("generation"),
               "op": operation}
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            deadline = time.monotonic() + timeout
            connection.settimeout(timeout)
            connection.connect(str(endpoint))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ControlError("control request deadline expired")
            connection.settimeout(remaining)
            connection.sendall(json.dumps(payload).encode() + b"\n")
            result = _read_message(connection, deadline)
    except OSError as exc:
        raise ControlError("benchmark control connection failed") from exc
    if result.get("ok") is not True:
        raise ControlError(str(result.get("error", "control request failed")))
    return result


class OwnedLauncher:
    """One local process group and its bounded readiness/output observation."""

    def __init__(self, command: list[str], project: Path, log_dir: Path,
                 url: str):
        self.ready = threading.Event()
        self.disconnected = threading.Event()
        self.stopped = False
        self.log_dir = log_dir
        marker = f"connected to fdbench at {url} · benchmark mode".encode()
        output = os.fdopen(os.open(
            log_dir / "launcher.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        ), "wb")
        try:
            self.process = subprocess.Popen(
                command, cwd=project, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUNBUFFERED="1"),
                start_new_session=True,
            )
        except BaseException:
            output.close()
            raise
        self.reader = threading.Thread(
            target=self._record, args=(output, marker), daemon=True,
        )
        self.reader.start()

    def _record(self, output, marker: bytes) -> None:
        # Keep a bounded tail even when a child emits huge/no-newline output.
        pipe = self.process.stdout
        if pipe is None:
            output.close()
            return
        with pipe, output:
            tail = b""
            size = max(len(marker), len(DISCONNECTED))
            while chunk := pipe.read1(4096):
                output.write(chunk)
                output.flush()
                observed = tail + chunk
                if marker in observed:
                    self.ready.set()
                if DISCONNECTED in observed:
                    self.disconnected.set()
                tail = observed[-size:]

    def _signal_group(self, sig: int) -> bool:
        try:
            os.killpg(self.process.pid, sig)
            return True
        except ProcessLookupError:
            return False

    def stop(self, timeout: float) -> None:
        if self.stopped:
            return
        self.stopped = True
        self._signal_group(signal.SIGTERM)
        deadline = time.monotonic() + timeout
        # Descendants can outlive a launcher that obeyed SIGTERM. Continue to
        # own the entire group instead of treating leader exit as cleanup.
        while time.monotonic() < deadline:
            self.process.poll()
            if not self._signal_group(0):
                break
            time.sleep(0.01)
        self._signal_group(signal.SIGKILL)
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ControlError("owned launcher did not exit after SIGKILL") \
                from exc
        self.reader.join(timeout=0.5)
        if self.reader.is_alive():
            raise ControlError("launcher output did not close after shutdown")


class BenchmarkServer:
    """Serial benchmark-only resets; each response names one lifetime."""

    def __init__(self, args):
        self.args = args
        self.generation = 0
        self.child: OwnedLauncher | None = None
        self.stopping = threading.Event()

    def state(self, *, ready: bool) -> dict:
        return {"instance": self.args.instance, "generation": self.generation,
                "ready": ready,
                "pid": self.child.process.pid if self.child else None,
                "log_dir": str(self.child.log_dir) if self.child else None}

    def save_state(self, *, ready: bool) -> None:
        path = self.args.control_dir / (STATE_NAME + ".tmp")
        with os.fdopen(os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
        ), "w", encoding="utf-8") as output:
            json.dump(self.state(ready=ready), output)
            output.write("\n")
        os.replace(path, self.args.control_dir / STATE_NAME)

    def start_child(self) -> None:
        self.generation += 1
        log_dir = self.args.log_root / f"session-{self.generation:06d}"
        log_dir.mkdir(mode=0o700)
        command = [self.args.python, str(self.args.launcher), "--url",
                   self.args.url, "--project", str(self.args.project),
                   "--once", "--wait", str(self.args.start_timeout),
                   "--log-dir", str(log_dir)]
        self.child = OwnedLauncher(
            command, self.args.project, log_dir, self.args.url,
        )
        self.save_state(ready=False)
        deadline = time.monotonic() + self.args.start_timeout
        while not self.child.ready.wait(0.01):
            if self.stopping.is_set():
                raise ControlError("benchmark wrapper stopped during startup")
            if self.child.process.poll() is not None:
                raise ControlError(
                    f"launcher exited before connecting: {log_dir}",
                )
            if time.monotonic() >= deadline:
                raise ControlError(f"launcher connection timed out: {log_dir}")
        if self.child.process.poll() is not None:
            raise ControlError(f"launcher exited while connecting: {log_dir}")
        self.save_state(ready=True)

    def stop_child(self) -> None:
        child, self.child = self.child, None
        if child is not None:
            child.stop(self.args.stop_timeout)

    def validate_request(self, payload: dict) -> str:
        if payload.get("instance") != self.args.instance:
            raise ControlError("stale or foreign benchmark instance")
        operation = payload.get("op")
        if (not isinstance(operation, str)
                or operation not in {"status", "reset", "stop"}):
            raise ControlError("unsupported benchmark control operation")
        generation = payload.get("generation")
        if (type(generation) is not int or generation != self.generation):
            raise ControlError("stale benchmark generation")
        return operation

    @staticmethod
    def reply(connection: socket.socket, result: dict) -> None:
        try:
            connection.sendall(json.dumps(result).encode() + b"\n")
        except OSError:
            # A bounded client can leave while startup/cleanup is in progress.
            pass

    def serve(self) -> None:
        self.args.control_dir.mkdir(mode=0o700)
        _private_directory(self.args.control_dir)
        endpoint = self.args.control_dir / SOCKET_NAME
        previous = {}
        with socket.socket(socket.AF_UNIX) as server:
            try:
                self.args.log_root.mkdir(mode=0o700)
                _private_directory(self.args.log_root)
                server.bind(str(endpoint))
                endpoint.chmod(0o600)
                server.listen(4)
                server.settimeout(0.05)
                for sig in (signal.SIGINT, signal.SIGTERM):
                    previous[sig] = signal.signal(
                        sig, lambda *_: self.stopping.set(),
                    )
                self.start_child()
                while not self.stopping.is_set():
                    child = self.child
                    if child is None:
                        raise ControlError("benchmark launcher ownership lost")
                    if child.disconnected.is_set():
                        break
                    code = child.process.poll()
                    if code is not None:
                        if code != 0:
                            raise ControlError(
                                f"benchmark launcher exited: {code}",
                            )
                        break
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        continue
                    with connection:
                        connection.settimeout(0.5)
                        try:
                            operation = self.validate_request(
                                _read_message(
                                    connection, time.monotonic() + 0.5,
                                ),
                            )
                        except (ControlError, OSError) as exc:
                            self.reply(connection, {"ok": False,
                                                    "error": str(exc)})
                            continue
                        try:
                            if operation in {"reset", "stop"}:
                                self.save_state(ready=False)
                                self.stop_child()
                            if operation == "reset":
                                self.start_child()
                            self.reply(connection, {
                                "ok": True,
                                **self.state(ready=operation != "stop"),
                            })
                        except (ControlError, OSError) as exc:
                            self.reply(connection, {"ok": False,
                                                    "error": str(exc)})
                            # Upstream ignores reset exit codes. Exiting closes
                            # the transport; never keep an old session alive.
                            raise
                        if operation == "stop":
                            break
            finally:
                try:
                    self.stop_child()
                finally:
                    endpoint.unlink(missing_ok=True)
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("serve", "reset", "status", "stop"),
    )
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--url", default="ws://127.0.0.1:8791")
    parser.add_argument("--log-root", type=Path)
    parser.add_argument("--start-timeout", type=float, default=40.0)
    parser.add_argument("--stop-timeout", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=55.0)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", args.instance):
            raise ControlError("instance must contain 8-64 letters/digits/_/-")
        # abspath preserves final symlinks for the ownership checks to reject.
        args.control_dir = Path(os.path.abspath(args.control_dir))
        if len(os.fsencode(args.control_dir / SOCKET_NAME)) >= 104:
            raise ControlError("use a short control directory under /tmp")
        if args.operation != "serve":
            result = request(args.control_dir, args.instance, args.operation,
                             timeout=args.timeout)
            print(json.dumps(result))
            return 0
        if args.project is None or args.launcher is None:
            raise ControlError("serve requires --project and --launcher")
        args.project = args.project.resolve(strict=True)
        args.launcher = args.launcher.resolve(strict=True)
        args.log_root = (args.log_root.absolute() if args.log_root
                         else args.control_dir / "sessions")
        for value, maximum in ((args.start_timeout, 40),
                               (args.stop_timeout, 4)):
            if not math.isfinite(value) or not 0 < value <= maximum:
                raise ControlError(
                    "startup/stop timeouts exceed bounded limits",
                )
        url = urlparse(args.url)
        if (url.scheme != "ws" or url.hostname not in {
                "localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/"}):
            raise ControlError("benchmark wrapper requires a local ws:// URL")
        BenchmarkServer(args).serve()
        return 0
    except (ControlError, OSError, ValueError) as exc:
        print(f"benchmark-control: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
