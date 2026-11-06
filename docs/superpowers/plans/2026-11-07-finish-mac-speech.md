# Finish the existing Mac speech service

Authority: `docs/ME3_SPEC_2026-11-04.md`; user requested completion of the
existing voice model, following D1. Continue the current feature checkout and
preserve operator settings, newer commits and unrelated untracked files.

Keep Whisper large-v3-turbo through MLX, Kokoro bf16 with `af_heart`, separate
speech service, Qwen foreground and Pi worker. No model/provider substitution,
new orchestration model, ownership bypass in normal voice mode, or changes to
the external benchmark scorer.

1. Reproduce bounded native model calls. Record initial failures/successes and
   cold/warm timings. Both configured models currently pass on the actual GPU;
   the old stalled runs remain historical failures, not overwritten results.
2. Write failing behavioral regressions for startup readiness and successful
   speech verification. Warm native models before serving requests; expose a
   bounded repeatable self-check with generated test audio and a safe receipt.
   Fail explicitly on invalid/nonempty audio and failed inference. Keep native
   role capacity occupied until actual inference finishes after cancellation.
3. Configure only the local speech-service token and matching client keys in
   ignored private `.env`; preserve foreground/Pi credentials. Verify real
   authenticated HTTP ASR/TTS and a Qwen speech roundtrip. Exercise real Pipecat
   scheduling with generated input; keep microphone/playback separate.
4. Run new and complete installed tests after changes, check startup/shutdown,
   save evidence and a synthetic voice sample, update setup/status, and commit
   coherent increments. Perform an independent final review. Leave unavailable
   physical/ownership/benchmark/hardware gates explicitly unpassed.

Ruling: This repairs and qualifies the already selected architecture; the
user's implementation instruction and approved November 4 spec supply the
design. No new design approval is needed. The current feature checkout is
reused under the desktop workspace instructions; no new worktree is created.

Evidence and working ledger: `.local/verification/d2/`.
