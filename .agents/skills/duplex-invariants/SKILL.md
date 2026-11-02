---
name: duplex-invariants
description: Use when changing floor control, harness adapters, speech, jobs or benchmark behavior.
---

Trace whether a change affects speech, foreground context, job revision or an
external action. They are not the same state. Preserve the older baseline.

Test blocked jobs alongside new foreground requests, speech-only interruption,
stale late results, provider failure, shutdown, and completion while ASR is still
pending. VAD silence alone is not end-of-turn. A backchannel must not automatically
cancel speech. Unknown addressee evidence is not proven background rejection.

Keep capture live during playback; bound queues and flush old output. Never call
TTS submission or generated text confirmed speech delivery. Test transport gaps,
late lifecycle events and actual double-talk before trusting playback receipts.

Hermes/Pi workers are local and isolated; only inference may be remote. Explicit
operator configuration selects commands and endpoints, never user speech or tool
output. No silent fallback or side effects in this restricted prototype.

Use the unchanged course scorer and identical runtime with a swapped transport.
Do not pass expected trial behavior, labels or judge outputs to the agent. State
clock/endpoints, counts, failures and conditions. Filler timing is not useful
response latency. Simulator timing is not acoustic or Raspberry Pi qualification.
