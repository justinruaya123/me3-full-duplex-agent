# Improve measured voice latency with the selected models

User authorized implementation from the real November 7 benchmark. Work starts
from85e7595 onhermes/benchmark-latency-v1; the prior feature branch and unrelated
untracked files remain intact. No model/credentials/billing/scorer changes.

## Evidence and design

The baseline's ASR final mean/p95 is4.454/5.231s. Actual native profiling on a
separate generated development phrase found three full encoder passes per ASR
request, each~.9s. Decode and word alignment have byte-identical mel input;
language detection uses different padding and must be computed independently.
Keep auto language detection and actual word timestamps. Use a single-entry
encoder memo only inside one native request; key exact shape, dtype and bytes,
restore the original encoder and release its key/features on success or error.
The service already serializes ASR and retains native capacity on cancellation.
No cache may span requests or let changed audio reuse older features.

## Implementation and verification sequence

1. Write failing behavioral tests for exact-input memoization, changed/mutated
   input, failures and request cleanup/restoration. Implement the small local
   request boundary with lazy optional imports, then full installed suite.
2. Run actual paired uncached/cached native tests with identical model and
   development audio. Require identical transcript/language/word timing output
   and fewer encoder evaluations. Retain all failed measurements.
3. Investigate partial/final scheduling separately. Implement a further bounded
   optimization only if independently supported, with RED/GREEN safety tests.
4. Restart and check the actual authenticated speech service, then freeze the
   code and rerun the same upstream57eaddbc benchmark, seed231,10phrases x3runs
   plusone duplex round. Keep course ownership bypass and default6s gaps for
   comparability; disclose context carry-over. Preserve the baseline unchanged.
5. Score real recordings with unchanged faster-whisper-small/Praat; no judge or
   UTMOS pass claims. Compare mean/p95, missing replies and WER with denominators.
6. Record code/model/source pins, native and benchmark receipts, exact tests,
   setup commands and remaining gates in DUPLEX_STATUS/BENCHMARK/SETUP. Commit
   coherent increments. No merge. Physical acoustics/Pi remain separate.
