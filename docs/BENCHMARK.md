# Benchmark methods and results

## Actual course run: November 7

The real Mac pipeline completed the supplied course benchmark at
`57eaddbc188ce9a19b8fd002b575f703426956f4`. Its scorer is unchanged; nine score
module hashes and clean external Git state are recorded with the evidence.
The older `106ac8e...` checkout remains intact. The final measured agent commit
is `11684782fd306f4f84dfaf0959f41c4076ca654e`.

Run `2026-11-07_01-34-42` used seed 231, 10 phrases repeated three times, then
one duplex round. All 40 queue items completed in 807.262 seconds, producing
44 recordings including four clean twins. There were zero transport errors
and zero scoring errors. This was actual Whisper/Qwen/Kokoro inference over
the direct WebSocket transport, with microphone and speaker closed.

| Metric | Default target | Mean | p95 | Samples | Upstream status |
| --- | --- | --- | --- | --- | --- |
| E2E, VAD end to output mark | 4.0s | 5.422s | 6.788s | 29 | Over |
| ASR final | 0.8s | 4.454s | 5.231s | 30 | Over |
| LLM first text | 1.5s | 0.335s | 0.890s | 29 | Met |
| TTS first audio chunk | 0.6s | 0.422s | 1.013s | 29 | p95 over |
| Barge-in stop | 0.8s | 0.380s | 0.380s | 2 | Met on these two samples |
| Corpus WER | 15% | 1.932% | Not applicable | 30 | Met |

The targets require both mean and p95 below the limit. WER was four edits in
207 reference words. Two of the 30 phrase trials had no speech in the recorded
response window. Missing timings are excluded by the upstream scorer, not
counted as successes. Recorded speech onset relative to true input speech end
was 5.836s mean / 6.982s p95 over 28 trials; that differs from the software
output-mark clock above. Neither clock is a physical acoustic measurement.

Other results: pause TOR 0/1 synthetic and 0/1 Candor; turn-taking TOR 1/1;
false turn-taking 2/2; interruption TOR 0/1. The two false-turn trials covered
side talk and TV/radio; idle background/noise strata have zero samples.
Backchannel/background trials paused and returned after 5.096s/6.020s.
Relevance and v1.5 content labels are unscored because no judge is configured.
Praat pitch/intensity and WPM ran, with only one paired interruption sample;
no statistical voice-change conclusion is supported. UTMOS was not installed
or scored.

The final run used one declared `course` profile, globally bypassing ownership.
The adapter never reads clip labels or expected answers. Models were
`mlx-community/whisper-large-v3-turbo`, `Qwen/Qwen3.8-27B`, and
`mlx-community/Kokoro-82M-bf16` / `af_heart`; Silero and SmartTurn v3.2 ran.
Pi.dev remains the default delegated worker, but this run did not exercise a
busy Pi job. Scoring ASR was separate: `faster-whisper/small`, CPU int8.

The default six-second silence gap does not reset context or incomplete capture.
Prior speech carried into some trials, and accumulated unfinished capture hit
the 16-second limit once and was explicitly discarded. These results are a
diagnostic continuous-session baseline, not independent per-clip qualification.
The fixed upstream report title mentions Raspberry Pi; its actual device card
is Darwin/16GB. No Raspberry Pi was tested. Mac resource sampling lacks GPU,
temperature/throttle data and labelled memory for the separate MLX service.

Reports, failed attempts, RED/GREEN tests and source pins are in
[the course evidence](evidence/2026-11-07/course-benchmark/README.md).

## Reproduce the real run

Use the installed pinned copy at `.local/fd-benchmark-20261107`, with its own
Python 3.12 environment. Fresh setup and exact launch commands are in
[SETUP](SETUP.md#course-benchmark). After starting `./scripts/me3.sh speech`,
load the operator environment in the project root:

```sh
set -a
. ./.env
set +a
export FDBENCH_PROJECT="$PWD"
export FDBENCH_ENTRY="$PWD/integrations/fdbench_entry.py"
export FDBENCH_ASSISTANT_PYTHON="$PWD/.venv313/bin/python"
export ME3_BENCHMARK_PROFILE=course
cd .local/fd-benchmark-20261107
.venv/bin/python -m fdbench run --student me3-local --rounds 1 \
  --phrases 10 --runs 3 --seed 231 --connect direct --where local \
  --judge-provider none --no-score --yes --recordings r --no-live
# Replace the run path with the folder printed by the new run.
.venv/bin/python -m fdbench score runs/me3-local/2026-11-07_01-34-42 \
  --judge-provider none --no-utmos --asr-model small
```

Keep raw recordings under the ignored benchmark checkout. No benchmark dataset
audio is copied into the project evidence. Preserve any missing/late replies
and failed runs. Do not change targets or substitute models to obtain passes.

## Next unpassed gates

1. Reduce ASR final delay while preserving complete-audio commits, provisional
   transcript restrictions and native capacity. Profile encode/decode/alignment
   and partial/final scheduling before choosing the optimization. Then repeat
   this pinned measurement; E2E and TTS p95 must also reach their targets.
2. Supply a hard fresh-session reset through the upstream `--reset-cmd` hook
   before independent trials. Handle long turns through bounded stitching;
   retain explicit fragment discard until that is implemented and tested.
3. Add and qualify independent addressee/overlap evidence. The course bypass
   currently treats committed speech as addressed; false-turn rates and long
   backchannel gaps remain failures. Do not use expected clip labels as input.
4. Configure an explicitly selected judge for content/relevance, add sufficient
   rounds per stratum, then qualify physical acoustics and actual Pi hardware.
   Two stop samples do not establish a reliable p95 or the spec's 250ms target.

## Control simulation, separate from the real run
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

For the delegated-job extension, run the same foreground trials with 0, 1 and 2
active workers. Test job completion during user speech, simultaneous completions,
explicit focus restoration, job revision, worker timeout, stale output, network
failure and cancellation races. Separate intentional notification waiting from
technical delay after an eligible conversational boundary.

Run Full-Duplex-Bench pause/overlap/turn-taking tracks and tool/disfluency tracks
as separate evidence. Pin the benchmark revision, corpus and configuration.
Add unfamiliar live speakers and real-device trials; do not mix mocked actions
with physical-device success. No benchmark assets are copied into this repository.

## Further qualification
Pi4/Pi5 audio behavior; physical ASR/LLM/TTS latency; semantic endpointing; AEC;
backchannel handling; speaker ownership; notification naturalness; safe actions;
real model-server contention; abrupt-crash orphan recovery; human acceptance.
