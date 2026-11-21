# Benchmark methods and results

## Conversation-return candidate: two complete canonical attempts

Frozen source **`ed6efa0dd9edaa6dceebf342392b54604bb43cbc`** on
`hermes/conversation-return-v1` adds durable result preferences, conservative
hesitation holds and neutral listening cues. Two complete runs used the same
unchanged canonical ME3 commit `57eaddbc188ce9a19b8fd002b575f703426956f4`, complete
official dataset, seed 231, ten phrases x three runs and three duplex rounds.
Fresh runtime hooks reset every recording, including clean twins. Both declared
the global course ownership bypass and used the original CPU-int8 small scorer
without judge or UTMOS. All 430 dataset references and nine scorer hashes match
the prior pin; runtime source hashes stayed identical before/after both runs.

Each completed **60/60 queue items and 72 recordings**, with zero transport or
scoring errors. These completion counts are not successful-response counts.
The original scorer's per-run means/p95s follow; no custom scorer or pooled
acceptance statistic is substituted.

| Metric, mean / p95 seconds | Prior baseline `06-10-46` | Attempt 1 `10-13-32` | Attempt 2 `10-39-12` | ME3 target |
| --- | --- | --- | --- | --- |
| E2E software output mark | 2.552 / 3.711 (n=29) | 2.725 / 4.241 (n=29) | 3.433 / 6.702 (n=19) | 4 |
| ASR final | 1.470 / 2.036 (n=30) | 1.507 / 1.965 (n=30) | 1.476 / 1.924 (n=30) | 0.8 |
| LLM first text | 0.402 / 0.745 (n=29) | 0.601 / 1.797 (n=29) | 1.296 / 5.435 (n=19) | 1.5 |
| TTS first PCM | 0.424 / 0.696 (n=29) | 0.402 / 0.744 (n=29) | 0.405 / 0.783 (n=19) | 0.6 |
| Interruption stop | 0.337 / 0.406 (n=3) | 0.252 / 0.252 (n=3) | 0.228 / 0.338 (n=4) | 0.8 |
| WER, percent | 1.449 (n=30) | 1.449 (n=30) | 1.449 (n=30) | 15 |
| Recorded phrase replies | 29/30 | 28/30 | 19/30 | Report all misses |

The new attempts **fail benchmark non-regression**. Both exceed E2E/LLM p95
targets, while ASR/TTS still exceed their existing gates. The second run is
retained, not replaced with only the better first attempt. The models and
foreground prompt/inference implementation were unchanged; these observations
do not establish a causal effect of the new policy on provider latency.

In attempt 1, the tennis phrase's first text arrived after a 6.721s stage wait;
its output mark was only about 97ms before recording ended, with no detected
recorded speech. Its 8.023s software E2E remains in the table's sample. The
other missing phrase had no first token before close. All eleven missing
phrase replies in attempt 2 likewise reached committed ASR and a foreground
request without a first token before close. Neither a hesitation veto nor a
listening cue explains those phrase failures. The request-to-first-text stage
includes client/network/server time; its precise root cause remains unqualified.

Digital heard-onset mean/p95 was **3.050/4.201s (n=28)** and **3.960/7.230s
(n=19)**, separate from software output marks and from physical acoustics.
No pre-answer cue/output credit was found in either attempt's stage traces;
the new listening-cue path was not exercised by these benchmark recordings.
Its separate Pipecat fixture and actual Kokoro HTTP checks are not benchmark
or natural-placement acceptance evidence.

Pause TOR remained 0/3 in both pause strata, and turn-taking TOR 1/3, in each
attempt. False-turn rates were 2/6 and 4/6 under the original threshold.
V1 interruption TOR was 1/2 played cases in attempt 1 (three scheduled) and
1/3 in attempt 2. Backchannel cases returned in 2/3 each; the same second-round
case did not return. No judge means response relevance/Resume labels remain
unknown. Stop timing had only 3 and 4 valid observations out of six scheduled
cases per run; missing/unplayed overlaps are not zero-latency successes.

See [all original reports, failures, pins and traces](evidence/2026-11-07/conversation-return/README.md).
Reproduce with the [existing fresh-session recipe](RASPBERRY_PI_TESTING.md#use-only-the-canonical-me3-benchmark),
using `--rounds 3 --phrases 10 --runs 3 --seed 231` for this comparison. Main
keeps the preceding baseline; the candidate remains available for explicit
feature/target testing. **Next gate:** diagnose and resolve repeatable
request-to-first-text delay and missing replies, then pass the same full ME3
run. Independent ownership, physical acoustics/AEC, long turns, soak and actual
RPi qualification remain separate and unpassed.

## Final canonical ME3 run: November 7

Run `2026-11-07_06-10-46` measured the published source `6bbbfd5`, using only
canonical ME3 `57eaddbc188ce9a19b8fd002b575f703426956f4`, its complete official
dataset and unchanged scorer. Seed 231, ten phrases repeated three times, three
complete duplex rounds, explicit global course bypass and a fresh runtime for
every recording completed **60/60 queue items / 72 recordings** in **1357.089s**.
Transport/scoring errors were zero. The target applies to both mean and p95.

| Metric | Mean | p95 | ME3 target | n | Observation |
| --- | --- | --- | --- | --- | --- |
| E2E, VAD end to output mark | 2.552s | 3.711s | 4s | 29 | Below on observed samples |
| ASR final | 1.470s | 2.036s | 0.8s | 30 | Over |
| LLM first text | 0.402s | 0.745s | 1.5s | 29 | Below on observed samples |
| TTS first PCM | 0.424s | 0.696s | 0.6s | 29 | Over |
| Interruption stop | 0.337s | 0.406s | 0.8s | 3 | Below on observed samples; n=3 is insufficient |
| Corpus WER | 3/207 = 1.449% | Not applicable | 15% | 30 | Below |

The headline clock is VAD-end to software output mark. Digital recorded speech
onset was **3.066s mean / 4.158s p95**, n=29. **29/30** phrase trials had recorded
replies. Missing timings are excluded by the unchanged scorer and are not passes.
Maximum software E2E was 6.304s, maximum LLM first text 4.609s. Three of six
scheduled interruption cases had a valid stop measurement; already-silent
cases are retained and excluded rather than credited as zero-latency stops.
Small samples do not establish a robust p95 or the spec's physical 250ms gate.

Turn-taking TOR was 1/3; interruption TOR 2/3; false-turn rate 2/6 under the
original word-count threshold. All three synthetic and three Candor pause
windows had no counted speech. Four of six false-turn recordings contain detected bot speech; short
replies can fall below that threshold. Independent addressee rejection remains
unqualified.
Two of three backchannel cases returned; one did not. The previously stuck
first-round acknowledgement returned after 1.832s without a new semantic ASR
commit; its control regression separately verifies retained bytes/context/epoch.
No content judge or UTMOS was used. Keep unjudged Respond/Resume labels unknown.

The preceding first fresh-session run, `2026-11-07_05-16-13` at `c321634`,
completed 40/40 items / 44 recordings. Its mean/p95 were E2E 3.287/6.140s,
ASR 1.462/1.958s, LLM 1.017/3.307s, TTS 0.465/1.128s and stop 0.316/0.345s
(n=2); WER 3/207=1.449%, with 29/30 recorded phrase replies. Setup/transport and
archive I/O may overlap its early trials; those observations are retained.
The final recording ran without those extra workloads. Provider and answer
variation still prevent attributing the whole-run LLM/TTS differences to code;
their model/prompt/inference paths were unchanged between these fresh runs.

Native Turbo feature reuse has separate paired development evidence: 20/20
text/language/word-field comparisons matched; 17 warm ordinary pairs averaged
1.824s -> 0.978s. The high-confidence language-input padding changed and broader
language equivalence remains unqualified. Neither native profiles, prompt
pilots nor control simulations are substitute benchmark results. Rejected
compiler/prompt candidates remain failures in the archive.

See [raw official reports, source pins and failures](evidence/2026-11-07/realistic-targets/README.md)
and [reproducible setup](SETUP.md#course-benchmark). The
[planned Pi procedure](RASPBERRY_PI_TESTING.md) uses the same canonical benchmark
and separates target runtime evidence from optional Mac evaluation compute.
No Pi hardware, physical acoustic p95, idle/busy audio comparison, speakerphone
qualification or 30-minute target soak was performed here. The fixed upstream
report title is a template; the measured device card is Darwin/16GB.

The immediate unpassed timing gates are **ASR <=0.8s** and **TTS p95 <=0.6s**.
Semantic turn/addressee/acknowledgement gates remain open even where timing is
below its threshold. Earlier continuous-session diagnostics are preserved below;
their context/reset protocol differs from the final independent recordings.

## Inference improvement: November 7

The optimized build `03e1ff7` reran the identical pinned protocol as
`2026-11-07_02-16-38`: all 40 queue items / 44 recordings completed and scored,
with zero transport or scoring errors. Selected model IDs, local speech weights,
voice, thresholds, seed, datasets and the external scorer were preserved.
Remote Qwen weights are provider-managed; its exact response model ID is checked.

| Metric | Baseline mean / p95 | Optimized mean / p95 | Default target |
| --- | --- | --- | --- |
| E2E | 5.422 / 6.788s | 3.639 / 5.077s | 4.0s |
| ASR final | 4.454 / 5.231s | 2.786 / 3.546s | 0.8s |
| LLM first text | 0.335 / 0.890s | 0.153 / 0.117s | 1.5s |
| TTS first audio | 0.422 / 1.013s | 0.471 / 1.122s | 0.6s |
| Barge-in, two samples each | 0.380 / 0.380s | 0.748 / 1.022s | 0.8s |
| Corpus WER | 1.932% (4/207) | 2.415% (5/207) | 15% |

Native encoder reuse reduced paired GPU inference from 2.838s to 1.937s mean
without changing any transcript/language/word timing fields in six development
pairs. The memo is one entry inside one request; auto language detection, full
context and real word timestamps remain. Capture reuse requires identical full
PCM in the current generation and still waits for SmartTurn before commitment.

Observed E2E mean improved 32.89% and ASR final mean 37.46%. Optimized phrase
coverage is 30/30 recorded replies, baseline 28/30; baseline software E2E, LLM
and TTS samples are 29, optimized 30. Digital heard-onset mean/p95 is now
4.151/5.524s versus 5.836/6.982s. Five versus four word errors is one extra edit,
not evidence of unchanged whole-pipeline WER. End-to-end mean now meets 4s;
its p95, ASR, TTS p95 and barge-in p95 still fail their gates.

Runs were sequential and host/provider load varied; improved LLM timings and
worse TTS timings cannot be attributed to this code change. Barge-in has only
two samples. In one slower case the mapped VAD mark was ~0.922s after stimulus
speech onset; old output ended ~0.130s later. The evidence retains that outlier,
clock limits and all content/turn failures. No detector threshold was tuned to
the benchmark. False turns remain 2/2; interruption TOR improved 0/1 -> 1/1
while turn-taking TOR fell 1/1 -> 0/1. Content/relevance judging and UTMOS remain
unscored. Physical acoustics and Pi qualification remain separate.

[Comparison, native checks, tests and official reports](evidence/2026-11-07/latency-improvement/README.md)
preserve the baseline below. Fresh-session resets, long-turn stitching,
addressee/detector qualification and larger samples are still required.

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
.venv/bin/python -m fdbench score runs/me3-local/2026-11-07_02-16-38 \
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

Use only the canonical ME3 benchmark's complete pause, overlap and turn-taking
groups with its original scorer for benchmark evidence. Keep development
regressions and provider probes separately labelled. Pin the benchmark revision,
official corpus and configuration.
Add unfamiliar live speakers and real-device trials; do not mix mocked actions
with physical-device success. No benchmark assets are copied into this repository.

## Further qualification
Pi4/Pi5 audio behavior; physical ASR/LLM/TTS latency; semantic endpointing; AEC;
backchannel handling; speaker ownership; notification naturalness; safe actions;
real model-server contention; abrupt-crash orphan recovery; human acceptance.
