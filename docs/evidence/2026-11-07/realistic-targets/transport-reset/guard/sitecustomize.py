"""Verification-only guard: the child may connect by TCP only to our WS port."""

import json
import os
from pathlib import Path
import socket
import sys


audit_root = os.environ.get("ME3_RESET_AUDIT_DIR")
allowed_port = os.environ.get("ME3_RESET_WS_PORT")


def record(value):
    path = Path(audit_root) / f"{os.getpid()}.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(value) + "\n").encode())
    finally:
        os.close(descriptor)


def audit(event, args):
    if event == "socket.connect":
        connection, address = args
        if (connection.family in {socket.AF_INET, socket.AF_INET6}
                and connection.type & socket.SOCK_STREAM):
            allowed = (address[0] in {"127.0.0.1", "localhost", "::1"}
                       and address[1] == int(allowed_port))
            record({"event": "tcp_connect", "allowed": allowed,
                    "loopback": address[0] in {"127.0.0.1", "::1"},
                    "port": address[1]})
            if not allowed:
                raise RuntimeError(
                    "Transport-only verification forbids provider TCP calls",
                )
    elif event == "subprocess.Popen":
        # Do not serialize argv or env: the operator environment has secrets.
        record({"event": "subprocess",
                "executable": Path(os.fsdecode(args[0])).name})


if audit_root and allowed_port:
    sys.addaudithook(audit)
    record({"event": "guard_installed", "pid": os.getpid()})
