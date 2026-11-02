# Harness-neutral duplex prototype

## Authority and scope
Continue the 2026-10-15 prototype on `perliminary` at
`6a044dba1edb0d0edba998954def39dbc0158d51`. The user's 2026-11-02 addendum
replaces OnIt with Hermes as the first harness and requires portability to Pi.
Do not change the separate ME2 smart-speaker, its model, or its grammar.
The standalone course rubric was not found by Project/Library search. The
requirements preserved in repository documentation, repository contracts, and
supplied benchmark are the basis of this increment, not an assertion of full rubric compliance.

## Design
Use Pipecat's audio pipeline, an independent conversation controller, and the
existing SQLite Supervisor. Only the controller may request speech. Background
workers return data, never audio or a synthetic user command. A completion notice
waits for a quiet boundary and never changes focus. Barge-in cancels foreground
work/playback, not jobs. Revision fencing and durable state stay in Supervisor.

Hermes and Pi implement the existing async `run(prompt, workspace,
foreground=False) -> str` interface. Each request is initially an isolated local
process. No model-selected executable, shell interpolation, implicit mock,
external-action tool, or remote autonomous harness. Only inference can leave the
orchestration host. Explicit mock use is permitted in tests/demo only.

## Alternatives and ruling
Pipecat is the first transport because the supplied benchmark already injects a
Pipecat transport. LiveKit is a later adapter, not a second controller. A native
speech-to-speech model is a comparison baseline, not a prerequisite. Do not
build a new audio framework or bind scheduling to Hermes internals.

## Prototype versus target
The first increment intentionally buffers a complete foreground answer before
TTS and uses final ASR plus conservative lexical overlap rules. Incoming brief
acknowledgments preserve playback; explicit stop commands interrupt. A separate
incomplete-turn signal can request a rate-limited outgoing backchannel. This is
not a trained acoustic policy, true streaming ASR, AEC, speaker ownership,
background-speech rejection, or a demonstrated GPT-Live equivalent.
Target: incremental ASR, acoustic/semantic floor policy, streamed clauses,
playback-confirmed prefix accounting, persistent isolated harness workers, and
reserved foreground inference capacity. Promote each only with measured evidence.

## Acceptance
Tests must cover backchannel versus command, idle acknowledgments, speech-only
cancellation, blocked jobs, stale foreground results, notification defer/retry,
no focus change, subprocess failure/timeout/reaping, strict JSONL, and no mock
fallback. An audio benchmark must use the identical runtime and only replace the
transport. No test labels, scenario IDs, or judge prompts may reach the agent.
