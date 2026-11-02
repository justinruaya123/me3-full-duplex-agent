# ME3 architecture and qualification plan — 2026-11-02

## Authority and recovered requirements

The current request selects Hermes, with interchangeable Pi support. Earlier
requirements were recovered from this repository's README, AGENTS.md, PLAN.md,
STATUS.md and duplex-invariants skill at `6a044dba...`. The formal course ME3
rubric and the complete other-chat transcript were not recovered by Project and
Library search. This document is therefore a project-continuation specification,
not a claim that every grading requirement has been checked.

Preserve the prior local-orchestration/inference-only-offload boundary; separate
speech interruption, foreground cancellation and explicit task cancellation;
retain durable jobs/revisions; do not mutate the earlier ME2 VCM. Hermes replaces
OnIt for the new voice entrypoint; old modules remain a historical baseline.

## Recommended end state

Use Pipecat first, because the supplied benchmark already accepts its transport
and frame lifecycle. Keep the policy in ordinary Python, independent of Pipecat,
LiveKit, Hermes and Pi. LiveKit remains a transport alternative for multi-client
rooms/WebRTC deployment, not a second stack to build in parallel for this demo.

A fast perception/control path consumes continuous AEC-cleaned audio, VAD,
incremental transcript revisions, addressee evidence, prosodic turn-completion
scores and actual playback state. It chooses WAIT, HOLD, BACKCHANNEL, RESPOND,
INTERRUPT, DELEGATE, or OFFER_RESULT. A VAD onset alone is not permission to cancel.

A separate conversational model produces short responses. It receives only
committed transcript context and the confirmed spoken prefix. A tool facade
submits long jobs to a bounded durable supervisor and returns an ID immediately.
Independent local Hermes/Pi sessions execute those jobs. Workers return artifacts
and status; they cannot call TTS. Completion queues a notice, not a new user turn.
A single speech arbiter chooses an idle, relevant moment to offer the result.
Only the user's acceptance changes focus or requests a fuller summary.

This is inspired by the publicly described fast-conversation/deeper-work split
in GPT Live. It does not reproduce an undisclosed native speech model or establish
matching behavior. Streaming ASR + LLM + TTS can be concurrently scheduled, but
its quality, semantic timing and prosody must be measured rather than inferred.

## Prototype boundary

| Area | Implemented increment | Still required |
|---|---|---|
| Audio | Optional Pipecat transport/VAD/REST ASR/TTS wiring | Installed-runtime and acoustic tests; AEC |
| Turn control | Exact user-backchannel phrases, explicit stops, pending-ASR floor protection | Acoustic/semantic classifier, addressee detection |
| Agent backchannels | Rate-limited `complete=False` response; optional lexical hold | Natural prosodic placement and user study |
| Jobs | Adapter to existing SQLite Supervisor | Re-run full persistence suite in complete checkout |
| Harnesses | Source-pinned Hermes runner; Pi JSONL protocol adapter | Real startup/provider smoke; persistent warm workers |
| Re-entry | Idle-boundary notices, no focus change, ack after receipt | Confirmed playback receipts, result relevance and spoken retrieval |
| Benchmark | Matching `build(transport, log_dir)` entry | Actual dataset run and scored recordings |

The lightweight component should be the controller/turn policy, not a newly
trained general speech-to-intent VCM squeezed into the ME2 parameter limits.
Start with existing ASR/TTS inference on the M2/LAN. Do not introduce a native
speech-to-speech backbone or train a new acoustic encoder before the modular
baseline establishes where latency and errors come from.

## How to reach the intended performance

First validate this boundary with the real pinned dependencies and providers.
Then replace process-per-request with separate warm foreground and worker
processes, preserve cancellation fencing, and reserve inference capacity for the
foreground. Two Python tasks do not create GPU capacity or prioritize inference.

Next use streaming ASR with stable-prefix/revision events. Start speculative
language generation only for reversible work; discard it when the transcript
changes. Stream short stable text chunks into TTS rather than buffering complete
responses. Attach output epochs and playback offsets to every audio segment.
Update conversation history with what was actually played, not everything generated.

Add a small turn/overlap classifier using acoustics, transcript context and
playback state. Compare simple rules with a learned policy on development data.
Keep task execution behind an allowlist and an approval boundary. Train/tune only
on development partitions, not the supplied benchmark's expected labels.

## Evaluation influence

Retain the course scorer unchanged. Record the benchmark commit, model identifiers,
source pins, machine, audio rates, endpoint topology, dataset revision, judge and
seed. Compare the old baseline, modular controller, controller plus backchannels,
and controller plus a busy worker using identical inputs and providers. Compare
a native speech-to-speech reference under the same rig separately.

Report pause TOR; missed and false turn-taking; genuine interruption response
quality; Resume/Respond behavior for backchannels/side talk/background speech;
t_stop and t_resp; p50/p95 first *substantive* audio latency. A filler is not task
completion. Report raw end-to-end timings and an echo-loop calibration separately;
do not silently subtract transport overhead. Include all failures and denominators.

Add a separate local job suite: converse while a worker is blocked, interrupt
speech without cancelling a task, explicitly cancel/update jobs, reject stale
results, finish a job while the user speaks, defer a notice while ASR is pending,
retry an interrupted notice, and verify the requested artifact is correct. These
are supplemental tests, not new definitions of the published benchmark metrics.

Proposed development targets (not results or recovered course requirements):
substantive turn-response p95 below 1 s, playback stop p95 below 250 ms after a
qualified interruption decision, and no inappropriate focus switches in the
job scenarios. Also measure onset-to-decision latency: reporting only the fast
post-decision stop would hide a slow classifier. Judge the aggregate trade-off,
not a single latency statistic or a successful canned demo.

A six-second silent interval does not reset model context. Specify a supported
fresh-session procedure per trial/run and audit carryover. Direct feed does not
qualify speakerphone echo cancellation or real-world double-talk; those require
a separate physical mic/speaker suite on the intended machine.

## Inspected primary sources

- Prior project implementation: https://github.com/justinruaya123/me3-full-duplex-agent/tree/6a044dba1edb0d0edba998954def39dbc0158d51
- Public GPT Live design: https://openai.com/index/introducing-gpt-live/
- Benchmark method and adapter: https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking
- Pipecat source: https://github.com/pipecat-ai/pipecat/tree/6f777a0ef3bb98163d10d708525a0db21cda5fbf
- Hermes constructor/API: https://github.com/NousResearch/hermes-agent/tree/2b31d7b283191b8069311fd3514ee89419f76516
- Pi RPC and CLI: https://github.com/earendil-works/pi/tree/3e0eec29f50e7861e9db91f2d12723267411b4f3/packages/coding-agent/docs
- LiveKit turn handling: https://docs.livekit.io/agents/logic/turns/
