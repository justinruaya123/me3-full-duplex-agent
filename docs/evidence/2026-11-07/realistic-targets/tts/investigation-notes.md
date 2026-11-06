# Private TTS investigation, November 7

No production files are changed by these diagnostics. The selected model remains
`mlx-community/Kokoro-82M-bf16`, voice `af_heart`, speed `1.0`, mono PCM16 at
24 kHz. No GPU/native/service/provider call has been run during preparation.
The root agent owns the exclusive GPU slot.

## Source findings to measure

1. `Model.generate()` caches its English pipeline but resets `pipeline.voices`
   on every request, so the same exact local voice tensor is loaded again.
2. `Model.__call__()` reads each predicted phoneme duration with `int(n)` in a
   Python loop. The first scalar read also waits for the preceding encoder and
   duration graph, so a line timer around this loop does not isolate scalar
   overhead from encoder compute. Only paired changes can establish benefit.
3. `KokoroPipeline.join_timestamps()` reads many MLX scalars and reductions with
   `.item()` after inference, even though the speech service exposes only PCM.
   A bulk host list can preserve timestamp metadata while avoiding those reads.
4. First PCM waits for the entire current phoneme segment's decoder evaluation.
   Voice caching or CPU phonemization alone may not explain p95. Full input
   context and weights must remain fixed while measuring inference changes.
5. `mx.clear_cache()` runs after every generated segment. Its cost is profiled,
   but no cache-clear removal candidate is included because bounded memory
   behavior needs separate justification.

## Bounded profiler

`profile_tts.py plan` imports no native libraries and makes no network calls.
It prints five generated development texts with 20, 69, 77, 171 and 276
characters. The numeric text includes `1,234.56` and a date. These sentences are
independent of benchmark labels or expected replies. Declared natural parts
are retained for later chunking experiments; the current native profiler
synthesizes every complete original input without changing text boundaries.

CPU preparation checks completed successfully:

- Python byte-compilation.
- `plan --repeats 2` (60 paired baseline/candidate requests planned, plus
  5 stage profiles, 1 line profile and 1 warmup).
- Exact source-marker guards and Python parsing/compilation for all three
  private one-variable variants, against the installed MLX Audio 0.6.4 sources.

After the root grants the exclusive GPU slot:

```sh
.speech-venv312/bin/python .local/verification/targets/tts/profile_tts.py native \
  --output .local/verification/targets/tts/native-v1 --repeats 2
```

The outer process enforces a 240-second total deadline and kills/reaps the
native process group on timeout. HF is offline, so missing local assets fail
instead of triggering downloads. The native request path matches the project's
model generation arguments and PCM conversion. Timing pairs alternate order,
use fixed seeds, and include no stage/line wrappers. Stage wrappers and the
line trace run in separately labelled passes. Stage durations are inclusive;
they must not be added together.

The native oracle checks every generated source grapheme (ignoring whitespace),
phoneme counts, every float audio sample, and every PCM byte against the exact
same complete-input baseline. Saved WAVs allow audition. It does not claim
pronunciation quality, speech recognition scoring, acoustic capture or benchmark
qualification. A candidate which changes even one float/PCM sample is reported
as a failed equality candidate; the script does not waive a failure.

Each candidate temporarily replaces one method in its private child only:

- `bulk-durations`: materialize `pred_dur.tolist()` once before the existing
  duration expansion loop.
- `cached-voice`: retain the already-loaded exact voice tensor instead of
  resetting its dictionary.
- `bulk-timestamps`: materialize integer durations once, then do the same
  timestamp sums and arithmetic on host integers.

The guarded source transforms are exploratory probes, not a proposed way to
maintain production code. No production recommendation is justified until the
stage and exact-output evidence exists.

The separate `http` subcommand uses the already-running authenticated loopback
service, reads credentials only from the inherited operator environment, and
never logs them. It refuses a different selected model or voice. It measures
headers and the first complete PCM sample, consumes the entire bounded response,
and saves each complete WAV. It has the same hard process deadline. Run only
after the root explicitly releases the service/GPU slot:

```sh
.speech-venv312/bin/python .local/verification/targets/tts/profile_tts.py http \
  --output .local/verification/targets/tts/http-v1 --repeats 2
```

Native/HTTP reports cannot substitute for the unchanged end-to-end benchmark.
This private profiler neither reads nor modifies the benchmark dataset/scorer.

## Native results after the exclusive slot was granted

The root stopped the speech service and reserved the native/GPU slot. The
bounded main profiler completed **30 pairs / 60 paired requests**, 5 separate
stage requests, 1 line-profile request and 1 warmup. It exited 1 because the
strict float/PCM equality oracle failed. The separate same-baseline control
completed 10 repeated-baseline requests, 2 excitation-RNG profiles and 1 warmup,
then exited 0. Both native children fully exited and the slot was released.
**80 total native synthetic-speech generations, zero HTTP/provider/acoustic
requests.** No production patch was made.

The loaded Kokoro snapshot was
`a71e4d38b236d968966a2002c4c895dbd12b1c3c`. Its local `af_heart` voice SHA-256
was `2c1c733b0e6576c810e268d3e440c21dea4e0f0131a3ba4cfc98d7fe6136d094`.
Installed distributions remained MLX Audio 0.6.4, MLX 0.32.4 and Misaki 0.9.4.
Reports, full profiles, controls and audition WAVs are in `native-v1/`.

Separately instrumented complete-input profiles:

| Text characters | Phonemes | First PCM | Model forward incl. eval | G2P | Voice load | Timestamp joining |
| --- | --- | --- | --- | --- | --- | --- |
| 20 | 19 | 0.1891s | 0.1851s | 1.67ms | 0.20ms | 1.63ms |
| 69 | 67 | 0.3895s | 0.3798s | 2.58ms | 0.30ms | 5.95ms |
| 77, with numbers | 127 | 0.6490s | 0.6380s | 3.04ms | 0.36ms | 6.60ms |
| 171 | 169 | 0.8434s | 0.8248s | 2.01ms | 0.12ms | 14.82ms |
| 276 | 270 | 1.3589s | 1.3232s | 3.98ms | 0.25ms | 29.22ms |

All five profile inputs had complete generated graphemes; all 30 pairs had
identical phoneme counts. First PCM is a complete generated native segment,
which explains why expanded numbers are slower than their character count
alone suggests. This is a native development profile, not a p95 benchmark or
an acoustic latency claim.

Each single-variable candidate had 10 alternating-order pairs:

| Candidate | Baseline mean | Candidate mean | Mean paired delta | Median paired delta |
| --- | --- | --- | --- | --- |
| Bulk duration reads | 0.7074s | 0.6854s | -22.00ms | -3.55ms |
| Retain exact voice | 0.6911s | 0.6877s | -3.43ms | +0.08ms |
| Bulk timestamp reads | 0.6877s | 0.6831s | -4.56ms | -0.83ms |

The duration mean is sensitive to a few slower baseline requests; its median
gain is only 3.55ms. These results do not justify an invasive model override.
The separate 270-phoneme line trace spent 1.2085s in final audio evaluation,
0.1144s in duration reads/index construction, 0.0179s constructing the graph
through predicted durations and 0.0153s in alignment/decoder graph construction.
The duration-loop interval includes waiting for the earlier duration graph;
it is not evidence of 114ms removable scalar overhead. Line tracing perturbs
execution and was excluded from the paired request means.

Strict equality failed in 30/30 candidate comparisons, but also in **5/5
unchanged-baseline controls** after resetting MLX, NumPy and Python RNGs. Every
module stayed in evaluation mode, and separately captured excitation RNG draws
were identical between controls. Baseline max absolute float differences were
7.45e-8 through 1.01e-7, with RMSE about 5e-9. The precise varying operation
was not isolated. Saved candidate/profile-baseline WAVs had equal lengths;
only 1–24 PCM samples differed per file, always by exactly one least-significant
PCM16 unit. This is evidence of tiny unchanged-path numerical variation, not
permission to label a failed bitwise check as a pass. No pronunciation-quality
equivalence claim is made from these arithmetic checks.

The main cost is whole-segment synthesis. Caching the voice cannot bring a
1.1-second tail under 0.6 seconds. A next project-owned change would need either
measured decoder optimization or earlier delivery of complete substantive
clauses. It should not change the model, voice, speed, text coverage or add a
filler. Before changing `clauses()`, use an output-boundary oracle across
arbitrary LLM token partitions: all source words remain in order, complete
numeric spans stay in one clause, abbreviations do not trigger early speech,
and output/cancellation queues remain bounded.

A CPU-only reproduction already found a current boundary hazard:

```text
Input deltas: 'The balance is 1,234.' + '56 dollars, and the receipt is ready.'
Current clauses: ['The balance is 1,234.', '56 dollars, and the receipt is ready.']
```

The identical text in one input delta preserves `1,234.56`. Likewise, `Dr.` at
the end of an intermediate delta emits before `Ellis` arrives. These examples
show why simply adding comma or character-count splitting is not an adequate
quality oracle. No production clause behavior was changed in this investigation.
