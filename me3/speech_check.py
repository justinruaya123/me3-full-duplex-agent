"""Bound a native speech self-check without importing audio dependencies."""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stop owned native threads and descendants holding output pipes."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def _read_report(process: subprocess.Popen, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError("Native speech check exceeded its deadline")
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                remaining = max(0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise TimeoutError("Native worker did not exit") from None
                return bytes(output)
            if len(output) + len(chunk) > 65536:
                raise OverflowError("Native speech check report is too large")
            output.extend(chunk)


def run_bounded_check(
    command: Sequence[str],
    expected: Mapping[str, str],
    *,
    timeout: float = 90,
) -> dict:
    """Stop a hung native call through its owned process."""
    if timeout <= 0:
        raise ValueError("Speech check timeout must be positive")
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True, bufsize=0,
    )
    try:
        output = _read_report(process, timeout)
    except TimeoutError:
        return {
            "passed": False, "error_type": "TimeoutError",
            "worker_pid": process.pid, "timeout_seconds": timeout,
        }
    except OverflowError:
        return {"passed": False, "error_type": "OutputLimitError"}
    finally:
        _terminate_tree(process)
        process.stdout.close()
    if process.returncode:
        return {
            "passed": False, "error_type": "WorkerExitError",
            "returncode": process.returncode,
        }
    try:
        if len(output) > 65536:
            raise ValueError("Oversized speech check report")
        report = json.loads(output)
        if not isinstance(report, dict) or report.get("passed") is not True:
            raise ValueError("No successful speech check report")
    except (ValueError, UnicodeError):
        return {"passed": False, "error_type": "InvalidReportError"}
    if any(report.get(key) != value for key, value in expected.items()):
        return {"passed": False, "error_type": "ModelSelectionError"}
    return report


def run_guarded_service(
    command: Sequence[str], *, startup_timeout: float = 90
) -> int:
    """Wait for a bound listener; stop the model process on timeout or exit."""
    if startup_timeout <= 0:
        raise ValueError("Speech startup timeout must be positive")
    read_fd, write_fd = os.pipe()
    process = None
    previous = signal.getsignal(signal.SIGTERM)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        process = subprocess.Popen(
            command,
            env={**os.environ, "ME3_SPEECH_READY_FD": str(write_fd)},
            pass_fds=(write_fd,), start_new_session=True,
        )
        os.close(write_fd)
        write_fd = None
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            if not selector.select(startup_timeout):
                return 2
            if os.read(read_fd, 16) != b"READY\n":
                return 2
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
        if process is not None:
            _terminate_tree(process)
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
