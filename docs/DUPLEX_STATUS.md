# Implementation and qualification status

## November 6: D1 model access and runtime lifetime gate passed

After the operator completed Pi sign-in, real inference succeeded with both
explicit selections: foreground `Qwen/Qwen3.8-27B` and worker
`openai-codex/gpt-6.1-sol`. No credentials, account settings, billing or models
were changed by verification.

- **Real foreground: 2/2 checks passed again.** Marker and arithmetic responses
  matched. First text arrived in 0.185469 s and 0.088029 s; full request times
  were 0.295845 s and 0.119244 s. The production adapter verified the exact
  response model, requested thinking disabled, and observed no reasoning or
  tool-call deltas.
- **Real Pi inference: passed.** `ME3_D1_PI_OK` returned in 4.600206 s after
  settlement. RPC selection matched before and after the request. The saved
  assistant response metadata also reports `openai-codex/gpt-6.1-sol` and normal
  `stop` termination, for both the smoke request and the job below. Worker
  tools/extensions/context discovery remained disabled.
- **Actual runtime with both real models: 9/9 checks passed.** A Pi prompt was
  in flight and its durable job was running while Qwen answered `42` in
  0.249421 s. `AgentRuntime.end_session` left that job running and the same Pi
  process alive. The job completed afterward with `ME3_D1_JOB_OK`; the ended
  session received no completion. Another owner could not retrieve it. The
  original owner reconnected and explicitly retrieved/delivered the result.
  This exercised trusted text sessions and the actual session-ending code;
  no physical voice capture, ASR, TTS or acoustic delivery was used.
- **Fresh installed full suite: 120 passed, 0 failures, 0 skips**, in 4.242 s.

Tested source: `94a0eeb1af36ca1ee0105d770f89bbf25362790d`. Receipts and methods
are in [the authenticated D1 evidence](evidence/2026-11-06/d1/authenticated/README.md).
The earlier authentication failure below is retained. These few text timings
are not p95 measurements or acoustic benchmark qualification. D1 is complete
at the model-access/runtime boundary; the next deliverable is D2, stable real
Mac Whisper/Kokoro inference and speech pipeline qualification. Real website
build/revision/browser verification, ownership, acoustic and Pi hardware gates
remain unpassed.

## November 6: initial D1 check before Pi sign-in

The operator configured foreground `Qwen/Qwen3.8-27B` and selected Pi worker
`openai-codex/gpt-6.1-sol`. These are explicit operator selections, not model
fallbacks. The foreground endpoint and credentials remain in the ignored `.env`.

- **Real foreground provider: 2/2 checks passed.** The exact marker and arithmetic
  requests returned `ME3_D1_FOREGROUND_OK` and `42`. First content arrived in
  0.181676 s and 0.080826 s; complete streamed requests took 0.291573 s and
  0.113699 s. The production adapter verified the exact response model ID,
  requested thinking disabled, and observed no reasoning or tool-call deltas.
  These are two text samples, not p95 or acoustic benchmark measurements.
- **Real controller with Qwen: 2/2 checks passed.** The actual runtime/controller
  delivered `ACK`, then recalled `amber falcon` on the second turn. Turn totals
  were 0.214655 s and 0.138173 s. Delivery was a text callback; no ASR, TTS,
  microphone or acoustic playback was exercised.
- **Pi provider inference: blocked, not passed.** Local RPC verified the exact
  selected provider/model, but the prompt was rejected: `No API key found for
  openai-codex.` The isolated Pi auth file has no entry for that provider and no
  worker API-key forwarding is configured. The supported next step is operator
  sign-in through `./scripts/me3.sh pi` and `/login`; no account, billing or model
  setting was changed. No successful worker inference or real website job is
  claimed.
- **Fresh installed full suite: 120 passed, 0 failures, 0 skips**, in 5.357 s.
  This is regression evidence, separate from the provider checks above.

Source tested: `2d8b7d25aa0f13d5a0feb16bdf1a380cb8fb551b`. Sanitized receipts
and the full suite log are in [evidence/2026-11-06/d1](evidence/2026-11-06/d1).
At this point D1 remained partial pending a real authenticated Pi request; the
later check above resolves that blocker. The separate Mac speech stalls and
ownership/acoustic/hardware gates below remain unpassed.

## November 4 implementation baseline

The active branch is `feat/pi-full-duplex-v1`, descended from prototype
`642cc73`. Pi.dev is the default worker; the controller remains harness-neutral.
This report supersedes the older verification notes preserved below.

## Implemented

1. Distinct worker/foreground configuration, explicit exact model selection,
   dependency-isolated runtime and long-lived job ownership independent of voice.
2. Bounded rolling ASR snapshots, timestamped revisions/stable prefixes/commits,
   cancellable streamed clauses, cross-session/epoch audio tokens, output fencing,
   and ordered whole-clause transport receipts. Provisional pause retains PCM.
3. Wake candidates, deliberate enrollment, session-local reference erasure,
   strict owner/addressee/overlap evidence, inactivity revocation, SmartTurn
   readiness and inference-independent local mute/stop controls.
4. Persistent per-job Pi RPC sessions, exact model/provider verification before
   prompting, settlement/error checks, tool-disabled generation and host-owned
   scoped static website builds with real Node syntax checks and hash receipts.
5. Durable owner-filtered/idempotent jobs; revisions/cancellation/results; grouped
   deferred notices; explicit focus and return; read-only revision-bound loopback
   previews; no model-returned command execution or automatic public deployment.
6. Setup/launch/diagnostic commands, isolated Mac speech service, optional AEC3
   playback-reference front end, declared benchmark profiles and recorded probes.

All implementation stages have code and regression coverage. **Full specification
acceptance is not complete.** The HTTP speaker-verifier adapter is an integration
boundary, not a bundled/qualified identity, overlap or addressee engine. Cached
outgoing Kokoro backchannels, calibrated uncertain-entity confirmation,
word-aligned heard-prefix accounting, long-dictation
stitching, licensed Krisp behavior, live-provider website/browser behavior and
all acoustic/target-hardware gates remain open.

## Test progression and independent review

| Stage | Full local suite | Evidence |
| --- | --- | --- |
| Configuration/runtime | 68 tests; 67 passed, 1 absent-Pipecat skip | stage1-suite.txt |
| Incremental/playback | 75 passed, 0 skips | stage2-suite.txt |
| Ownership/turns | 83 passed, 0 skips | stage3-suite.txt |
| Pi/static websites | 90 passed, 0 skips | stage4-suite.txt |
| Results/context | 98 passed, 0 skips | stage5-suite.txt |
| Final integration | **120 passed, 0 failures, 0 skips** | stage6-suite.txt |

Every stage has preceding RED evidence. The final independent reviewer found
five material issues: idle ownership expiry, speech suppression with running
focus, preview reconnect lifetime, silent provider failures and repeated-request
deduplication. Regressions reproduced each; fixes also cover late enrollment
across mute and bounded speech-service admission, including native calls still running after
HTTP cancellation. Further regressions fence
cross-session playback tokens, failed-probe readiness, ASR snapshot overflow,
completed-job queue capacity and duplicate active revisions.
Model output containing host-command text is verified inert.

An intermediate 114-test run failed the existing legacy console's unchanged
three-second process-start timeout during host slowdown. That failure is retained
in `stage6-contention-failure.txt`; a subsequent quiet run passed 114/114 without
relaxing its timeout. The final receipt includes later regressions and formatting.
Global Python initially had MCP 2.x, incompatible with the declared MCP <2;
that failed run is retained. Current tests use the installed isolated MCP 1.30.0.

## Actual local measurements, separate from simulations

- Installed Pi 0.84.2 accepted RPC and reported exactly
  `openai-codex/gpt-5.6-sol`. No provider prompt was used for this check. The
  isolated auth directory has not been signed in; account entitlement/inference
  remains unverified. Installed provider documentation supports ChatGPT
  subscription sign-in and explicitly selected API-key providers.
- Pipecat source `6f777a0...` installed and its API smoke ran. The scheduling
  regression runs actual Pipecat processors with fixture inference/in-process
  transport; it proves receipt ordering, not acoustic delivery.
- macOS enumerated 7 audio devices (5 with input, 5 with output capability).
  A one-second simultaneous native input/output smoke captured 15,360 input
  frames and played 24,000 silence frames; zero callback status errors. Input
  samples were immediately discarded; no microphone recording was saved.
- Real bundled SmartTurn ONNX synthetic-silence smoke completed in approximately
  0.365 s in the initial probe. Its COMPLETE output on that artificial clip is
  not a behavioral score; readiness still requires usable committed ASR.
- Actual WebRTC AEC3/reference-adapter smoke processed 50 synthetic 20ms frames
  in approximately 0.399 s including adapter/import overhead. No physical echo
  reduction, voice preservation, double-talk or acoustic stop latency was measured.
- MLX speech dependencies installed separately: Python 3.12.13, mlx-whisper
  0.4.3, mlx-audio 0.6.4 and Misaki 0.9.4. Misaki rejects Python 3.13; that
  concrete installation blocker and its Python-3.12 resolution are recorded.
- Exact Whisper large-v3-turbo weights were downloaded, preserving the cached
  smaller Whisper models. Kokoro uses the cached requested bf16 model. A real
  synthetic roundtrip stalled before the first Kokoro PCM and was stopped;
  separate exact-model Whisper inference exceeded a hard 45-second bound and
  was terminated. **Neither is passed.** There is no valid live speech latency
  or successful MLX roundtrip result. See mlx-roundtrip.json and whisper-probe.txt.
- Simulator benchmark: 20 trials per idle/busy-worker track, with artificial
  model delays and request-to-text clocks. Its metrics/source hashes are in
  simulation-final/metrics.json (and the earlier simulation/ receipt). These timings are explicitly not acoustic/model
  latency and cannot establish the <=250ms or <=1s proposed p95 targets.

## Benchmark and deployment

The external benchmark was fetched at
`106ac8e543a5fd996e254a87e69fa101bfd27a42`. Its launcher/rate check returned READY
for 16kHz input/24kHz output. The scorer was not edited; all score-module hashes
and clean external Git state are recorded in benchmark-scorer.json. No dataset,
judge or scored acoustic run was executed. Course ownership bypass is global;
end-to-end ownership must be evaluated separately, with wake/verification enabled.

No Raspberry Pi was attached or qualified. No 30-minute soak, controlled
idle/busy M2 contention qualification, accents/replay ownership dataset or physical
speakerphone test was run. Mac software/device smoke cannot qualify the Pi4.
The standalone course rubric and second Markdown attachment were not available;
the attached November 4 spec and the user's six stage names were used.

## Next unpassed acceptance gate

**Stable real Mac speech inference and pipeline qualification.** Resolve the
recorded Kokoro/Whisper stalls, choose the speech service token in `.env`, and
run the actual end-to-end headphone pipeline. Independently, supply the exact
foreground endpoint/model/API settings and authenticate Pi, then verify real
foreground/Pi inference and a built/revised website. Live owner mode additionally
requires a real authenticated speaker/overlap/addressee verifier service.
Do not turn missing credentials or these unpassed implementations/tests into
simulation successes. Setup/launch commands and remaining boundaries are in
[SETUP.md](SETUP.md). Evidence lives under `docs/evidence/2026-11-04/`.

---

# Historical prototype verification

# Duplex prototype verification — 2026-11-02

## Observed in this implementation session

The new overlay test suite ran on Linux/Python 3.13. Three initial test batches
first failed because their implementation modules did not exist. After
implementation, a self-review identified a pending-ASR race. Two regression tests
reproduced it: VAD silence could release a notice or an older response before the
new transcript arrived. Both passed after separating acoustic silence from
finalized-turn permission.

The final new suite has **31 tests: 30 pass, 1 explicit skip**. The skipped test
requires real Pipecat imports. Tests cover lexical policy, pending-ASR/floor races,
independent jobs, stale response fencing, deferred/retried notices, errors, bounded
subprocess output, cancellation/reaping, timeout, Pi settled-event handling, and
explicit provider configuration. Subprocesses are fixture programs, not Hermes/Pi.

`python -m me3.duplex_demo` ran successfully and asserted five control invariants.
It is an in-memory simulation. Compile checks passed for the new source, tests
and benchmark entry. New Python source lines are at most 79 characters; no
external style checker was available. No independent reviewer agent was available;
the review was performed in the implementation session.

## Not verified

- The old repository's full test suite was not rerun locally: the environment
  could read GitHub through the connector but could not clone/install through
  shell networking. The overlay preserves the old Supervisor unchanged.
- Pipecat was not installed; pipeline execution, provider behavior and actual
  playback receipts were not run. The API smoke test is honestly skipped.
- Real Hermes/Pi startup and inference, live microphone/speaker, MLX/Kokoro
  compatibility, AEC, M2/Pi4 throughput and network contention remain unmeasured.
- No Full-Duplex-Bench dataset was executed or scored. There are no acoustic
  latency results, no human acceptance result, and no speech-to-speech parity claim.
- The formal ME3 rubric and full other-chat transcript were not retrieved. Prior
  requirements came from the committed project documentation and this request.

## Publication and review scope

The new branch builds on `perliminary` at `6a044dba...`; it does not rewrite main,
rename old branches, replace the old SQLite supervisor or modify the benchmark.
The source pins are inspected compatibility targets, not a transitive dependency
lock. A source-compatible build still needs an installed-runtime smoke test.

First qualification: install the exact sources and actual providers; run the
full repository tests; run the optional Pipecat smoke; test microphone with
headphones; test interruption flushing and transport receipts; then run one
course-benchmark round with recordings and failure denominators. Replace per-call
process startup and buffered ASR/LLM only after preserving this regression suite.

## Post-publication CI and pipe-cleanup correction

GitHub Actions run `41455864296`, job `125312236109`, tested the complete
repository on Ubuntu/Python 3.12.15: **60 tests, 59 passed, 1 skipped**. The
existing SQLite/persistence suite and actual MCP SDK smoke passed, as did the
legacy demo, simulator benchmark and compile checks. Pipecat remained absent.

Although CI concluded success, its logs exposed an unclosed stdout transport
after the output-limit test. A new regression reproduced the issue locally:
the child had exited but stdout had not reached EOF. Teardown now closes stdin
and drains unread stdout concurrently with process termination, then waits for
both output pipes instead of cancelling the stderr reader prematurely.

After this correction, the local new suite reports **32 tests, 31 passed,
1 skipped**, with ResourceWarning reporting enabled and no cleanup warning in
the captured log. The deterministic demo and compilation also passed. This
supersedes the local counts above. The initial CI receipt applies to commit
`2629613`; the correction requires its own subsequent CI receipt. Neither run
provides live audio, real Hermes/Pi inference or acoustic benchmark evidence.
