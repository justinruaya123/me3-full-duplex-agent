# Benchmark boundaries

## Implemented now
`python -m me3 benchmark` is an explicit simulator experiment. It uses an
artificial 10 ms foreground wait and an artificially blocked background job.
The measured interval is local monotonic request submission to returned text.
Nearest-rank p50/p95, success/failure denominators, per-trial records, interpreter
metadata and source hashes are recorded. Output directories are immutable.
These numbers test plumbing and reporting, not model or acoustic performance.

## Subsequent classwork protocol
Measure user-turn end to first *useful audible* response, interruption onset to
last audible old response, correction end to relevant response, and authorization
to verified task state. Record the acknowledgements separately from useful output.
Use independent annotated speech boundaries, not the evaluated VAD as ground
truth. Playback submission and TTS first-byte times are internal diagnostics only.

Record user/stimulus reference and acoustic output on a shared recorder clock.
Calibrate channel offsets. Pair this with monotonic Pi events and stable session,
turn, utterance, job and revision IDs. Never subtract unsynchronized host clocks
or add component p95 values to invent an end-to-end p95.

For the OnIt-specific extension, run the same foreground trials with 0, 1 and 2
active workers. Test job completion during user speech, simultaneous completions,
explicit focus restoration, job revision, worker timeout, stale output, network
failure and cancellation races. Separate intentional notification waiting from
technical delay after an eligible conversational boundary.

Run Full-Duplex-Bench pause/overlap/turn-taking tracks and tool/disfluency tracks
as separate evidence. Pin the benchmark revision, corpus and configuration.
Add unfamiliar live speakers and real-device trials; do not mix mocked actions
with physical-device success. No benchmark assets are copied into this repository.

## Unqualified until measured
Pi4/Pi5 audio behavior; ASR/LLM/TTS model latency; semantic endpointing; AEC;
backchannel handling; speaker ownership; notification naturalness; safe actions;
real model-server contention; abrupt-crash orphan recovery; human acceptance.
