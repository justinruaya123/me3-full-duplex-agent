"""Bound a native speech self-check without importing audio dependencies."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence


def run_bounded_check(
    command: Sequence[str],
    expected: Mapping[str, str],
    *,
    timeout: float = 90,
) -> dict:
    """A hung native thread is stopped with its owned process, not just a task."""
    if timeout <= 0:
        raise ValueError("Speech check timeout must be positive")
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return {
                "passed": False,
                "error_type": "TimeoutError",
                "worker_pid": process.pid,
                "timeout_seconds": timeout,
            }
        except BaseException:
            process.kill()
            process.wait()
            raise
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
