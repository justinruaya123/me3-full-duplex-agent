# Independent final evidence audit

Reviewed November 7, 2026, against measured runtime
`6bbbfd57d5e5c062ec3846762158118a7318b0db`. This audit read the current README,
`DUPLEX_STATUS`, `BENCHMARK`, `SETUP`, `RASPBERRY_PI_TESTING`, archive index,
pins, official reports and underlying observations. No Important/Critical
defect was found within these checks. No tests, native inference, provider
requests or hardware experiments were run for this audit.

## Preservation and provenance

- Before adding this file, all **876 entries** in [sha256.json](sha256.json)
  matched their file bytes, with no missing, mismatched or unlisted files other
  than the deliberately excluded manifest itself. The final manifest must be
  regenerated to include this audit and any subsequent verification receipt.
- Both archived official run packages match their ignored original directories
  under `.local/fd-benchmark-20261107/runs/me3-local/`: **195 files** for
  `2026-11-07_05-16-13` and **312 files** for `2026-11-07_06-10-46` were
  byte-identical. This includes `results.json`, HTML, CSV, summary, chart,
  stage-latency report, session and queue. Both separately captured `score.log`
  files also match their original verification logs. The archived wrapper
  session logs match their original private log roots: **88/88** and **144/144**
  files respectively.
- All **60 current runtime/test/integration file hashes** in [pins.json](pins.json)
  match. Git reports no difference from measured `6bbbfd5` in `me3`, `tests` or
  `integrations`. The external benchmark remains clean at
  `57eaddbc188ce9a19b8fd002b575f703426956f4`; all **nine scorer hashes** match.
  Its complete dataset manifest matches
  `de429e12b486b752849ab029cf9c303cc3565bb8ce64e2fcf624844d3010e1a8`.
- Both run metadata records preserve Whisper large-v3-turbo, Qwen3.8-27B,
  Kokoro-82M-bf16/`af_heart` and worker `openai-codex/gpt-6.1-sol`.
  Recorded local model hashes are development-time receipts; this audit did
  not rehash weights or independently verify remote provider weights.

## Independent numerical checks

Recomputed means and linear-interpolated p95s directly from the final run's
30 [phrase observations](me3-runs/2026-11-07_06-10-46/stage_latency.json) and
per-recording timing JSON. They reproduce the published rounded values:

| Metric | Mean | p95 | Valid observations |
| --- | --- | --- | --- |
| Output-mark E2E | 2.552s | 3.711s | 29 |
| ASR final | 1.470s | 2.036s | 30 |
| LLM first text | 0.402s | 0.745s | 29 |
| TTS first PCM | 0.424s | 0.696s | 29 |
| Interruption stop | 0.337s | 0.406s | 3 |
| Digital recorded onset | 3.066s | 4.158s | 29 |

The queue is **60/60 completed**, zero skipped/failed, with **72 recordings**
(60 main and 12 clean twins). There are 72 timing files and 71 stage JSONL
files; the absent stage file is retained as absent. Corpus WER independently
recomputes to **3 edits / 207 reference words = 1.449%**, over 30 phrase trials.
The missing recorded phrase reply is
`r03_stage_latency_phrase_v15_background_91`; coverage remains **29/30**.
The maximum E2E 6.304s and LLM 4.6093s observations remain included.

Only **three of six scheduled interruption cases** have non-null stop times
(0.252s, 0.348s, 0.412s). The other three were already silent at interruption
onset and are not credited as zero-latency successes. The unchanged official
false-turn count is **2/6**, while **4/6** timing records contain detected bot
segments. The main documents disclose both denominators and the word-threshold
distinction. Small stop samples do not establish a reliable p95.

## Interpretation and retained failures

The reviewed documents distinguish Mac direct-feed/software timing from
physical acoustics, actual Raspberry Pi installation/audio, independent
ownership/addressee qualification and semantic acceptance. None is credited
from these runs. Judge/Respond/Resume and UTMOS remain unscored; cancelled or
custom subsets are not acceptance evidence. Setup/Pi examples remain planned
target procedures, with no concrete broken command found in the source review.

The archived post-run [full suite](full-suite/final.txt) records **208 tests in
14.958s, OK**; the [v1 receipt](full-suite/paused-backchannel-v1.txt) records
**178 tests in 10.532s, OK**, with no skips. These are inspected receipts, not
new audit executions. The earlier [independent source review](review.md)
states the scope of the floor-control and five Pipecat-fixture evidence.

The ASR confidence/padding heuristic is explicitly limited to its 20 paired
development comparisons; it is not universal language or quality parity.
`single-native.json` is valid JSON with `passed: false`; the compile/single
wrapper `InvalidReportError` records alone do not establish whether rejection
was framing or a reported failure. The TTS compiler's PRNG-continuation failure
and the foreground prompt quality failures remain rejected, with no promotion
or credit for unreached checks.
