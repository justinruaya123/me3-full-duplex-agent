# Real course benchmark: Mac direct feed, November 7

The actual Qwen/Whisper/Kokoro pipeline completed and was scored. It does not
meet the complete course latency gate. This is Mac software/direct-feed
evidence, separate from simulation, physical acoustics and Raspberry Pi tests.
The upstream report's fixed title mentions Raspberry Pi; its device card
correctly records Darwin/16GB. No Raspberry Pi was attached.

## Reports and exact scope

- [Official HTML report](results.html), [JSON](results.json),
  [CSV](results.csv), [slide summary](summary.md),
  [latency chart](latency_chart.svg), [per-turn stages](stage_latency.json).
- Benchmark source `57eaddbc188ce9a19b8fd002b575f703426956f4`, unchanged scorer.
  [Pins](pins.json) record the nine score-module hashes and clean Git state.
  The older `106ac8e...` checkout is preserved.
- Measured agent `11684782fd306f4f84dfaf0959f41c4076ca654e` on
  `feat/pi-full-duplex-v1`; optional stage instrumentation is `4ec8997`.
- Run `2026-11-07_01-34-42`, seed 231, global `course` ownership bypass.
  No clip labels, expected answers, judge output or per-clip settings enter
  the agent. The configured model IDs were not changed.
- 10 phrases x 3 runs, followed by one duplex round: **40/40 queue items,
  44/44 recordings including four clean twins**, 807.262208s. Zero transport
  errors and zero scoring errors. [Run events](events.jsonl) retain all trials.
- Real streaming Qwen inference; local warm MLX speech; Pipecat transport,
  Silero and SmartTurn v3.2. No microphone or speaker was opened. Pi.dev remains
  the default delegated worker; this run did not include an active worker job.

| Role | Exact selection |
| --- | --- |
| Foreground | `Qwen/Qwen3.8-27B`, separately configured inference endpoint |
| Agent ASR | `mlx-community/whisper-large-v3-turbo`, HF `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` |
| Agent TTS | `mlx-community/Kokoro-82M-bf16`, HF `a71e4d38b236d968966a2002c4c895dbd12b1c3c`, voice `af_heart` |
| Scoring ASR | `Systran/faster-whisper-small`, CPU int8, HF `536b0662742c02347bc0e980a01041f333bce120` |
| Content judge | None configured; not scored |
| UTMOS | Not installed; not scored |

The dataset release `datasets-v2/fdbench-datasets-v2.zip` was checksum-verified
by the upstream fetch tool: 430 audio files in nine downloaded directories.
The manifest hash is in pins.json. Exact installed distributions are in
[runtime environment](runtime-environment.json) and
[scorer environment](scorer-environment.json). The benchmark venv uses Python
3.12.13, faster-whisper 1.2.1 and Praat/parselmouth; the agent uses Python
3.13.6 / Pipecat 1.15.1.dev12. The separate MLX service pins remain in
[the D2 evidence](../d2/README.md).

## Unmodified scorer results

| Metric | Default target | Mean | p95 | n | Official status |
| --- | --- | --- | --- | --- | --- |
| E2E, VAD end to output mark | 4.0s | 5.4218s | 6.7883s | 29 | Over |
| ASR final | 0.8s | 4.45371s | 5.230725s | 30 | Over |
| LLM first text | 1.5s | 0.334869s | 0.8903s | 29 | Met |
| TTS first audio | 0.6s | 0.422048s | 1.01256s | 29 | p95 over |
| Barge-in stop | 0.8s | 0.380s | 0.380s | 2 | Met on these samples |
| Corpus WER | 15% | 1.932367% | Not applicable | 30 | Met |

Targets require both mean and p95 under the limit. Four word edits / 207
reference words; 30 observations repeat only 10 unique phrases. Two phrase
trials had no recorded speech in their response window. Missing stage samples
are excluded by the external scorer and must not be counted as passes.
Recorded output speech onset, relative to actual input speech end, was
5.836s mean / 6.9816s p95 over 28 trials. The software E2E mark and recorded
speech onset are distinct measurements, and neither is a physical acoustic
capture. No component p95 values are added to fabricate an E2E result.

Duplex results, with their small denominators:

- Pause TOR: 0/1 synthetic, 0/1 Candor; turn-taking TOR: 1/1, latency 5.272s.
- False turn-taking: 2/2 (one side talk, one TV/radio). Idle background/noise
  groups have zero samples this round. Prior-response carry-over limits the
  attribution of these failures to individual independent inputs.
- v1 interruption TOR: 0/1 despite a measured stop. v1/v1.5 interruption stop
  times were both 0.380s; two observations cannot establish reliable p95.
- v1.5 interruption, backchannel and background speech paused and returned
  after 4.518s, 5.096s and 6.020s. The talking-to-other trial had no initial
  answer, so its overlap was not played; its clean twin also had no reply.
- Relevance and Respond/Resume/Uncertain/Unknown content labels were not
  judged. Timing is not a substitute for those labels.
- Real WPM/Praat pitch/intensity features ran with one interruption pair;
  p-values are unavailable. No voice-change direction/significance pass is
  claimed. UTMOS has no data.

Host CPU median/p95 were approximately 22%/31%; lowest available RAM was
2376MB. Mac temperature, GPU load, clock and throttle information were absent.
The labelled assistant process memory excludes the separately started MLX
service. Its reported 186MB is not total system memory or Pi qualification.
Context size is the adapter's characters/4 estimate, not provider token usage.

## Bugs fixed and all earlier attempts

The first full attempt disconnected at a phrase containing a brief pause:
native ASR was running, one final waited, speech resumed, and another final
overflowed the two-slot queue. The fix cancels only superseded waiting work;
the in-flight native request retains its slot and its stale result is fenced.
A newer final also replaces a queued partial from the same capture generation.
Same-generation duplicate-final overload still invalidates authorization.

- `9c1064e`: stale queued-final retirement. [RED](queue-red.txt),
  [GREEN](queue-green.txt), [full suite](queue-suite.txt): 135 passed, no skips.
- `1168478`: queued partial supersession, following read-only review.
  [RED](queue-followup-red.txt), [GREEN](queue-followup-green.txt),
  [full suite](queue-followup-suite.txt): 136 passed, no skips.
- Independent read-only follow-up found no remaining Important/Critical
  findings in this fix. It did not run providers or simulate physical audio.
- [Final installed suite](final-suite.txt): **136 passed, zero failures,
  zero skips**, 4.190s. Required simulator, compile, lint and diff checks are
  separate from the real benchmark.

Earlier attempts are preserved in [earlier-attempts](earlier-attempts):

| Attempt | Result retained |
| --- | --- |
| `01-21-40`, one-phrase smoke | No recorded speech; all-zero output despite software transport receipts; unexplained, failed |
| Isolated transport probe | 25 chunks / 48,000 bytes, peak 1000; actual upstream WebSocket/project pipeline with fixture inference only |
| Real TTS nonsilence probe | 190,800 bytes, peak 11,615, 0.520430s; synthetic text, no acoustic capture |
| `01-26-54`, retry | Captured real reply at 6.532s; no source change between smoke attempts |
| `01-27-28`, pre-fix full attempt | Stopped after 12/40 items: nine phrase replies, one disconnection error and two connection errors |
| `01-33-01`, first fix | Stopped after 3/40 replies to add the second reviewer-identified regression; no crash |
| `01-34-42`, final build | All 40/40 items / 44 recordings completed, no disconnections; all scored, zero scoring errors |

These earlier successes are not pooled into the final run's denominator.
The first silent smoke remains unexplained; no source fix is claimed for it.

## Reproduction and evidence storage

From `/Users/jus/Documents/Grad/AI231/ME3`, start the warm speech service:

```sh
./scripts/me3.sh speech
```

In a second terminal, with the existing private operator .env:

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
# Use the newly printed run path for a new run. The measured scoring command:
HF_HUB_OFFLINE=1 .venv/bin/python -m fdbench score \
  runs/me3-local/2026-11-07_01-34-42 --judge-provider none \
  --no-utmos --asr-model small
```

Fresh installation commands are in [SETUP](../../../SETUP.md#course-benchmark).
Raw public-stimulus/assistant recordings remain under
`.local/fd-benchmark-20261107/runs/me3-local/2026-11-07_01-34-42/trials/`.
No dataset audio or microphone recording is committed here. Reports and
per-trial timings/stages are copied without editing; sha256.json inventories
this evidence. No credentials, billing or model selections were changed.

## Next unpassed acceptance gate

ASR final and E2E remain over target; TTS p95 remains over. Profile actual
native encode/decode/alignment and partial/final scheduling, preserve exact
model IDs and committed-transcript safety, then repeat this pinned test.
Independent per-clip qualification also needs a hard fresh-session reset via
the external `--reset-cmd` hook. Six-second silence did not clear unfinished
capture/history; prior speech carried over and one accumulated turn hit the
16s cap and was discarded. Long-turn stitching is still unimplemented.
Addressee/overlap qualification, a configured judge, more rounds, physical
acoustic p95, busy-worker contention and actual Raspberry Pi qualification
remain separate unpassed gates. The spec's 1s/250ms acoustic targets are not
established by this course run.
