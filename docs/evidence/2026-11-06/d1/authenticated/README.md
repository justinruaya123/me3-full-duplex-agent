# Authenticated D1 verification — November 6, 2026

Tested source: `94a0eeb1af36ca1ee0105d770f89bbf25362790d`.
Provider run started at `2026-11-06T13:21:02Z` (21:21:02 Asia/Manila).
No code, model selection, credentials or billing settings were changed by tests.

| Track | Result | Receipt |
| --- | --- | --- |
| Real Qwen provider | 2/2 passed | `foreground.json` |
| Real Pi/Sol provider | Exact marker passed; 4.600206 s including process startup and settlement | `pi.json` |
| Pi assistant model metadata | Exact provider/model in both real assistant responses | `pi-response-models.json` |
| Actual runtime/supervisor with real Pi and Qwen | 9/9 checks passed | `job-lifetime.json` |
| Installed regression suite | 120 passed; 0 failures; 0 skips; 4.242 s | `full-suite.txt` |
| Configuration diagnostic | Later voice prerequisites still block overall readiness | `configuration.json` |

The foreground selection was `Qwen/Qwen3.8-27B`; its production adapter checked
all response model IDs, sent `chat_template_kwargs.enable_thinking=false`, and
observed no reasoning or tool-call deltas. Marker and arithmetic first-content
times were 0.185469 s and 0.088029 s, with total streamed request times of
0.295845 s and 0.119244 s. These few text samples do not establish p95, audio
latency, dataset scores or target-hardware performance.

The Pi selection was `openai-codex/gpt-6.1-sol`, authenticated separately by the
operator. The production adapter checked selection before/after the smoke
request and awaited `agent_settled` before returning its text. Assistant metadata
in both saved sessions confirmed the same provider/model and `stop` termination.
Raw Pi sessions and credentials were not copied into this evidence directory.

## Job/session lifetime method

Used `AgentRuntime`, its durable supervisor/owner bindings, real configured
`PersistentPiBackend` and real `ForegroundBackend`. The only delivery callback
was text; no simulated worker, ASR, TTS or audio device was used.

1. Submitted `Reply with exactly ME3_D1_JOB_OK. Do not use tools.` through the
   trusted session's job interface.
2. Observed the actual outbound Pi RPC prompt, then checked the job was running.
   No artificial delay or worker-release fixture was introduced.
3. Sent `What is 17 plus 25? Reply with exactly the number.` through the actual
   controller. Qwen delivered `42` in 0.249421 s while the Pi job remained running.
4. Called `AgentRuntime.end_session`; checked the job stayed running and its Pi
   process was still alive with the same PID.
5. Waited for actual completion and the exact worker result. Confirmed the
   ended session received no completion delivery.
6. Opened another owner's session and confirmed job access was denied. Reopened
   the original owner's session, retrieved the result and explicitly delivered
   it using `/result JOB_ID`.

All nine recorded boolean checks passed. This validates the shared runtime
session-ending path at the text/control boundary. It does not qualify physical
voice shutdown or speaker authentication; the owner bindings are trusted local
operator identities.

## Reproduce access and launch

With the private `.env` and completed Pi sign-in:

```sh
cd /Users/jus/Documents/Grad/AI231/ME3
./scripts/me3.sh doctor --inference
./scripts/me3.sh console
```

The combined doctor's overall readiness can remain false even when both model
requests pass: wake and real speaker/overlap/addressee verification are still
unconfigured. Its provider results must be assessed separately from voice
readiness. The Mac speech stalls recorded in `DUPLEX_STATUS.md` are also unpassed;
configuration inspection does not exercise speech models.

In the console, `/task REQUEST`, `/jobs`, `/status JOB_ID`, `/end`,
`/start local-operator`, and `/result JOB_ID` exercise the same job/session
interfaces. End a session while its job is still running; `/quit` deliberately
shuts down the runtime and is a different operation. An independently timed
manual run may finish before `/end`; it does not reproduce an in-flight end.

Reproduce the installed regression suite separately:

```sh
.venv313/bin/python -m unittest discover -s tests -v
```

Next unpassed deliverable: D2, stable real MLX Whisper/Kokoro inference and the
headphone speech pipeline. Real website build/revision/browser behavior,
ownership, acoustic targets and Raspberry Pi qualification remain separate gates.
