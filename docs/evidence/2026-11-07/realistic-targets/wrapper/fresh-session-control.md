# Fresh benchmark session control

This explicitly invoked integration owns only the benchmark launchers. It never
changes ordinary voice-session/job cancellation. The external benchmark at
`57eaddbc188ce9a19b8fd002b575f703426956f4` is read-only and unchanged.

Plan: first fail new lifecycle tests, then implement one standard-library control
parent. Keep `--assistant-cmd` alive while `--reset-cmd` serially replaces its
owned `launch_assistant.py --once` process group. Every generation uses a new
private log tree, from which ME3 creates its new runtime. Observe the unchanged
launcher's actual connected marker before acknowledging. Reject old instances,
generation replays, unrecognized operations and nonprivate control paths. Bound
startup and TERM/KILL cleanup; fail closed on a reset startup failure.

Pinned upstream inspection: custom assistant commands are `shlex.split` with no
automatic `--log-dir` addition. Reset commands run with `shell=True`, 60-second
timeout, and ignored exit status. DirectRig permits reconnects and clears its
playout buffer for a newly connected assistant. Normal end closes the transport
and waits 15 seconds for the custom parent before SIGKILL. The wrapper observes
the launcher's disconnect marker and bounds hung child cleanup below this wait.

The control directory is new and exclusive, mode 0700, with a mode-0600 Unix
socket/state. Use a short `/tmp` path for macOS's Unix socket path limit. The
instance ID fences prior invocations; directory/socket ownership is the local
authorization boundary. Never reuse a control directory after exit.

Abrupt SIGKILL of the wrapper cannot run Python cleanup on macOS and can leave
its launcher running. Ordinary TERM/INT, explicit stop, reset, launcher failure
and transport disconnect perform bounded process-group cleanup. No guardian or
claim of abrupt-crash orphan recovery is included.

RED: `.venv313/bin/python -m unittest discover -s tests -p
'test_benchmark_control_v1.py' -v` failed before implementation with one import
error, `ModuleNotFoundError: No module named 'integrations.benchmark_control'`.
The tests use tiny owned Python programs plus real local TCP/Unix sockets; no
provider, model, microphone, dataset scoring or target-hardware claim is made.

The first postimplementation run in the restricted sandbox failed 10 tests
(8 failures, 2 errors) because local Unix/TCP socket binds returned
`PermissionError: [Errno 1] Operation not permitted`. A direct fixture diagnostic
confirmed the wrapper exited at the denied bind. With local socket capability,
the unchanged focused suite passed 10/10 tests, zero skips, in 3.333 seconds.

Two added regressions then failed (12 tests, 2 errors): a nonstring JSON operation
could crash the server with unhashable input, and a FIFO state file could block
the client before validation. Validate operation type before set membership;
open state with `O_NOFOLLOW | O_NONBLOCK` and validate its descriptor. The expanded
focused suite then passed 12/12 tests, zero skips, in 3.661 seconds.

CLI pairing (substitute an absolute ROOT and a new 8-64-character RUN_ID; quote
each path when composing the upstream command strings):

```sh
# The single command string passed to --assistant-cmd:
ROOT/.venv313/bin/python ROOT/integrations/benchmark_control.py serve \
  --control-dir /tmp/me3bc-RUN_ID --instance RUN_ID \
  --project ROOT --launcher ROOT/.local/fd-benchmark-20261107/launch_assistant.py \
  --log-root ROOT/.local/verification/targets/sessions-RUN_ID
# The single shell command string passed to --reset-cmd:
ROOT/.venv313/bin/python ROOT/integrations/benchmark_control.py reset \
  --control-dir /tmp/me3bc-RUN_ID --instance RUN_ID
```

Both directories must be new. The parent owns creation; the log-root parent
directory must already exist. Existing operator environment, including the
selected benchmark profile and provider configuration, is inherited unchanged;
the wrapper only forces unbuffered launcher output. It does not read `.env` or
auth files. `status`/`stop` use the same control-dir/instance arguments. Defaults
are 40s startup, 2s TERM grace plus at most 2s leader reap, and a 55s client
timeout. CLI maxima (40s startup / 4s cleanup per phase) leave room below the
upstream 60s hook timeout for both old/new process cleanup on a failed reset.
The normal disconnect marker stops even a launcher
whose own cleanup hangs.

Final boundary verification adds invalid/oversized JSON, all timeout values
(`0`, negative, NaN, positive/negative infinity, and greater than 55s), and slow
trickled requests. Each message has one monotonic deadline; receiving another
byte cannot extend the server's 0.5s request budget. The public request function
rejects invalid timeouts before touching files or sockets and shares one
deadline across connect/send/read.

- Timeout RED receipt: `fresh-control-timeout-red.txt` (one test, six subtest
  errors before timeout validation; 0.004s).
- Slow-request RED receipt: `fresh-control-deadline-red.txt` (one test, one
  control-client timeout error before a fixed message deadline; 1.163s).
- Final GREEN receipt: `fresh-control-green.txt`, from
  `.venv313/bin/python -W error::ResourceWarning -m unittest discover -s tests
  -p 'test_benchmark_control_v1.py' -v`: **15 passed, 0 failures, 0 skips**,
  4.329s. No ResourceWarnings occurred.
- `.venv313/bin/python -m compileall -q integrations/benchmark_control.py
  tests/test_benchmark_control_v1.py` passed. New Python lines are at most
  79 characters, with no trailing whitespace.

The root agent owns complete-suite integration and an actual unchanged-launcher
transport reset check. This handoff does not claim provider smoke, dataset
scoring, acoustic capture, model latency or hardware qualification. No commit,
external benchmark edit, main-document edit or normal voice behavior change was
made by this subtask.
