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
