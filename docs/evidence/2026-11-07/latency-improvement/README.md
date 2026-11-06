# Measured latency improvement with the selected models

Actual Mac inference and an unchanged course benchmark rerun, November 7.
Selected model IDs, local speech weights, voice, credentials, billing,
benchmark labels, thresholds and scorer were preserved. Remote Qwen weights
are provider-managed; its exact response model ID was checked, not its weight
files. Pi.dev remains the default worker. This run exercises
foreground voice with global course ownership bypass and no active worker job.
No microphone, physical speaker or Raspberry Pi was opened/tested. The fixed
upstream report title says Raspberry Pi; its device card records Darwin/16GB.

## Reports and provenance

- [Official HTML](results.html), [JSON](results.json), [CSV](results.csv),
  [summary](summary.md), [latency chart](latency_chart.svg),
  [per-turn stages](stage_latency.json), [comparison JSON](comparison.json).
- Baseline: [run 2026-11-07_01-34-42](../course-benchmark/README.md), agent
  `1168478`. Its reports and failed attempts are preserved unchanged.
- Optimized run: `2026-11-07_02-16-38`, frozen agent
  `03e1ff79de7e126c7fc6f2693fb1bfde8e2c00bd`, branch
  `hermes/benchmark-latency-v1`.
- External benchmark `57eaddbc188ce9a19b8fd002b575f703426956f4`, seed 231,
  10 phrases x 3 runs plus one duplex round. **40/40 queue items, 44 recordings,
  zero transport errors, zero scoring errors**, 797.846987s. Queue completion
  is distinct from a passed behavioral/latency verdict.
- [Pins](pins.json) include exact model/revision IDs, dataset manifest hash and
  nine unchanged score-module hashes. External Git state remained clean.
  Reports are copied byte-for-byte; no dataset/benchmark recording audio is
  committed here. Raw recordings remain in the ignored benchmark run folder.
  Upstream terminal padding and CSV CRLF are retained. They trigger whitespace
  warnings in an all-artifact diff check; source and authored documentation
  are checked separately so raw evidence is not normalized.
- Agent models: `mlx-community/whisper-large-v3-turbo`, `Qwen/Qwen3.8-27B`,
  `mlx-community/Kokoro-82M-bf16` / `af_heart`; Silero and SmartTurn v3.2.
  Scoring used real `faster-whisper/small` CPU int8 and Praat. Judge and UTMOS
  remain unscored. The prior evidence contains environment distribution pins;
  this change added no dependencies.

## What changed and what was tested

Commit `87c3336` adds a request-local one-entry encoder memo. Profiling found
three full encoder passes, each ~0.9s; decode and word alignment receive
byte-identical mel tensors. The language-detection input has different padding
and is independently evaluated. Exact shape/dtype/bytes key the memo. The
original encoder is restored and the memo's inputs/features released on every
exit. ASR remains serialized in the existing native executor, including after
HTTP cancellation. Full context, automatic language detection and real word
timestamps remain enabled. Heavy imports remain lazy/outside the portable core.

The [native profile](native-profile.json) and
[six paired real GPU checks](native-paired.json) use generated development
speech, separate from benchmark clips: full readiness phrase, its 0.8s prefix,
and an arithmetic question, two repetitions with alternating order. They show
three -> two encoder evaluations and mean **2.837908s -> 1.936673s**, a
**31.76%** reduction. Transcripts, detected language and all word timing and
probability fields were exactly equal in every pair. These are warm native
measurements, not acoustic p95 or multilingual qualification. Subsequent edits
to this module before the benchmark freeze shortened a docstring only.

Commit `03e1ff7` also avoids another recognition call when full PCM and capture
generation are identical to the last validated recognition. Final commitment
still waits for SmartTurn; changed PCM/new generation requires fresh ASR.
Begin, overflow, invalidation and close erase that memo. Provisional text still
cannot authorize actions, and stale generations remain fenced. Native queue
capacity and the earlier snapshot-overflow protections remain unchanged.

| Verification | Result and receipt |
| --- | --- |
| Encoder RED/GREEN | [3 errors before module](encoder-red.txt) -> [3 passed](encoder-green.txt) |
| Encoder stage installed suite | [139 passed, zero skips, 4.301s](encoder-suite.txt) |
| Snapshot RED/GREEN | [1 failure in 8 tests](snapshot-red.txt) -> [8 passed](snapshot-green.txt) |
| Snapshot stage installed suite | [141 passed, zero skips, 4.312s](snapshot-suite.txt) |
| Final installed suite | [141 passed, zero failures, zero skips, 4.475s](final-suite.txt) |
| Resumption verification | [141 passed, zero failures, zero skips, 4.622s](resumed-suite.txt) |
| Real HTTP speech | [6/6 passed](http-roundtrip.json): auth/model rejection, exact catalog, generated phrase/question, word timestamps and concurrency |
| Native paired comparison | [6/6 equal outputs, fewer encoder evaluations](native-summary.json) |
| Source review | No remaining Important/Critical findings; source inspection only |

The existing queued-final race fixture now adds fresh PCM before its first
final, so it still tests a genuinely running native final after memoization.
The final-turn test blocks SmartTurn approval and verifies no committed event
appears before approval. Tests are control evidence; the native/HTTP/benchmark
rows provide separate real inference evidence.

When the interrupted task resumed, the speech service process was absent and
the first catalog probe failed to connect. The owned service was restarted
with the existing configuration; its warm-up completed and the authenticated
exact-model catalog check passed. [Final checks](final-checks.json) and the
[resumed service log](resumed-service.txt) record the current state. That
restart is separate from the completed benchmark measurements above.

Warm sequential HTTP ASR took 2.022s/1.952s. TTS first PCM was 0.599s/0.270s.
Concurrent ASR/TTS completed in 2.198s/2.201s to ASR/first TTS PCM, showing
remaining shared-resource contention. Synthetic inputs only; no human audio
was captured or retained.

## Complete benchmark comparison

| Metric | Target | Baseline mean / p95 | Optimized mean / p95 | Current status |
| --- | --- | --- | --- | --- |
| E2E, VAD end to output mark | 4.0s | 5.422 / 6.788s | 3.639 / 5.077s | Mean met, p95 over |
| ASR final | 0.8s | 4.454 / 5.231s | 2.786 / 3.546s | Over |
| LLM first text | 1.5s | 0.335 / 0.890s | 0.153 / 0.117s | Met |
| TTS first audio | 0.6s | 0.422 / 1.013s | 0.471 / 1.122s | Mean met, p95 over |
| Barge-in stop | 0.8s | 0.380 / 0.380s | 0.748 / 1.022s | Mean met, p95 over; n=2 |
| Corpus WER | 15% | 1.932% (4/207) | 2.415% (5/207) | Met |

Observed E2E mean improved **32.89%**, ASR final mean **37.46%**. All optimized
software stage rows have 30 samples; baseline E2E/LLM/TTS have 29. Recorded
speech onset relative to actual input speech end improved **5.836/6.982s ->
4.151/5.524s** mean/p95. All 30 phrase trials now had recorded speech, versus
28/30 before. Missing timings were never counted as successes.

Word errors increased by one edit, 4 -> 5 across 207 reference words. The same
career phrase alternated between "changing" and "do" among repetitions in
both runs. No corpus-specific correction or score normalization was added.
Whole-pipeline WER is distinct from the native exact-input equality check.

Duplex outcomes remain mixed and have very small denominators:

- v1 interruption TOR 0/1 -> 1/1; turn-taking TOR 1/1 -> 0/1. The latter reply
  was three words, "I'm all ears", and failed the unchanged taking-turn rule.
- False turns remain 2/2; synthetic and Candor pause TOR remain 0/1 each.
  Idle background/noise false-turn strata still have zero samples.
- v1.5 background response gap fell 6.020s -> 4.036s. Talking-to-other initial
  and clean turns now had speech, while both baseline trials were silent;
  responding correctly to the overlap remains unjudged.
- One backchannel trial stopped without returning (timing-certified Unknown).
  Other Respond/Resume/Uncertain/Unknown content labels and interruption
  relevance remain unjudged. Timing does not establish semantic correctness.
- Barge-in samples were 1.052s and 0.444s versus 0.380s/0.380s. These two
  observations cannot establish a reliable p95. The slow case's
  [mapped timing diagnostic](interruption-timing.json) places VAD start about
  0.922s after stimulus speech onset, with old output ending ~0.130s later.
  Wall duration differs from digital audio duration by ~0.073s. Detector delay
  is an inference from this one trace, not a physical acoustic measurement or
  justification to tune thresholds on the held-out clip.

Runs were sequential, with uncontrolled provider/host load and generated reply
content. Host CPU median/p95 was 26%/57% versus 22%/31%; lowest available RAM
was 1830MB versus 2376MB. GPU/temperature/throttle and separate MLX-process
memory are unavailable. Improved LLM and worse TTS timings cannot be attributed
to this code change. The native alternating comparison is the more direct
evidence of encoder-compute reduction. Context size remains a chars/4 estimate.

## Reproduction and remaining gates

No new API settings or dependencies are required. Start the updated authenticated
service from the project root with `./scripts/me3.sh speech` (it remains running
in the implementation session). Existing `.env` model/auth selections are used.

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
# Use the newly printed folder for a new run; the measured scoring command:
HF_HUB_OFFLINE=1 .venv/bin/python -m fdbench score \
  runs/me3-local/2026-11-07_02-16-38 --judge-provider none \
  --no-utmos --asr-model small
```

Fresh environment commands are in [SETUP](../../../SETUP.md#course-benchmark).
The course profile bypasses ownership globally. Six-second gaps still permit
history and unfinished-capture carry-over; no hard reset was introduced to
change the comparison protocol. The new native code is not a fresh-session,
speaker/addressee, long-dictation or acoustic qualification.

Next unpassed gates: ASR final <=0.8s, E2E p95 <=4s, TTS p95 <=0.6s, robust
interruption p95 <=0.8s, meaningful response/backchannel behavior, independent
fresh sessions and sufficient per-stratum counts. Current measured native ASR
is still ~1.9s. Judge/UTMOS, busy-worker contention, physical acoustic p95 and
Raspberry Pi qualification remain separate. The spec's 1s/250ms acoustic
targets are unpassed. No merge was performed.
