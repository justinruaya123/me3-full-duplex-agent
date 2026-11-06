# Realistic benchmark targets implementation plan

> Use test-driven implementation and verification before completion. Independent
> components may be delegated; native GPU measurements are serialized.

Goal: reach the course mean/p95 targets where practical on this M2, retaining
Whisper Turbo as a hard constraint, unchanged scorer and honest quality gates.
The starting point is c528a41 on hermes/benchmark-latency-v1, 141 passing tests.

## Constraints and target method

- Preserve Whisper Turbo, selected foreground/TTS/worker IDs and credentials.
  No new billing, no implicit model fallback or benchmark-specific labels.
- Keep full context, real word timestamps and automatic language detection
  unless a separate language profile is explicitly declared and evaluated.
- Final actions require committed, owner-verified speech; stale sessions,
  generations, results and audio cannot gain authority through optimization.
- Speech/foreground/job cancellation remain separate. Mute/close erase voice
  state. Keep queues and child-process cleanup bounded and explicit.
- External benchmark57eaddbc code/scorer unchanged. Record profiles, dataset,
  seed, clock and all missing replies/errors. Do not optimize just a filler.
- Course mean+p95: E2E4s, ASR.8s, LLM1.5s, TTS.6s, interruptionstop.8s;
  WER15%. Physical1s/250ms and Pi qualification remain separate.

## Work sequence

1. Profile native Whisper compute while retaining its exact weights. Inspect
   the installed full encoder attention and supported MLX fused kernel. If a
   numerical/quality-checked improvement exists, write RED restoration/scope
   regressions, implement minimal encoder-only acceleration, then full suite.
   Verify real development speech, language and word-alignment quality before
   production benchmarking. Do not discard decoder cross-attention matrices.
2. Independently profile Kokoro startup, phonemization, scalar synchronization
   and text-length costs on generated development sentences. Implement only
   supported gains with complete text/audio and cancellation tests.
3. Add a trusted local benchmark wrapper using upstream --assistant-cmd and
   --reset-cmd to get a fresh controller/capture/runtime per independent trial.
   Keep normal voice-session job lifetime behavior unchanged. Test bounded
   child cleanup, restart failures, owner-only control and stale requests.
4. Measure Silero confidence, smoothed volume and minimum onset duration on
   independent speech/noise. Choose provisional-pause budgets only from that
   evidence; preserve SmartTurn/ASR/owner commit and backchannel behavior.
5. Freeze each candidate and run real stage benchmarks. Reject quality/safety
   regressions; preserve old/failed reports. Run final independent full-duplex
   tests with sufficient interruption counts to assess p95 realistically.
6. Keep iterating while safe measured changes remain useful. If a target is
   blocked by this hardware or missing independent identity/judge services,
   record the measured limit precisely, continue independent work and do not
   claim that gate passed. Update status/setup/evidence and commit increments.

## Review focus

- A fused kernel must never remove word-alignment cross-attention data.
- New startup/streaming paths must not hold native capacity after completion
  or admit concurrent native work after cancellation.
- Fresh benchmark reset must not kill ordinary delegated production jobs.
- Short interjections and background noise need separate onset/false-pause
  evidence; a VAD onset is not permission to execute/cancel a job.
- First audible speech can be filler; meaningful response and content judging
  must remain distinct from internal first-byte timing.
