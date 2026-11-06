# Improve measured voice latency with the selected models

The user authorized implementation from the real November 7 benchmark. Work
started from `85e7595` on `hermes/benchmark-latency-v1`; the previous feature
branch and unrelated untracked files remain intact. Model IDs, weights, voice,
credentials, billing and the external scorer were preserved.

## Design and evidence

The baseline ASR final mean/p95 was 4.454/5.231s. Actual native profiling on a
separate generated development phrase found three full encoder passes, each
about 0.9s. Decode and word alignment have byte-identical mel input; language
detection has different padding and is independently evaluated. A single-entry
request-local memo keys exact shape, dtype and bytes, restores the encoder,
and releases its key/features on success or error. Existing native capacity
retention after cancellation remains unchanged.

Capture additionally reuses one validated recognition only for identical full
PCM in the same generation. It still requires SmartTurn approval before final
commit, and clears on new generation, invalidation and close.

## Completed implementation sequence

- [x] Encoder reuse: failing regressions, implementation, full installed suite.
- [x] Real paired native checks: six pairs, identical transcript/language/word
  fields, 3 -> 2 encoder evaluations, 31.76% mean improvement.
- [x] Identical-snapshot reuse: failing commit-safety regression, changed-audio
  and generation coverage, full installed suite; no provisional authorization.
- [x] Restart and verify real authenticated HTTP ASR/TTS, six checks passed.
- [x] Freeze code at `03e1ff7`; repeat unchanged benchmark `57eaddbc`, seed 231,
  10 phrases x 3 runs plus one duplex round. All 40 queue items / 44 recordings
  completed. Retain course ownership bypass and default gaps for comparison.
- [x] Real faster-whisper-small/Praat scoring; no judge or UTMOS success claim.
- [x] Final installed suite: 141 passed, zero failures/skips, 4.475s. Record
  native, HTTP and benchmark evidence, source pins, reproduction and limits.

## Observed result and remaining gates

E2E mean 5.422 -> 3.639s; ASR final mean 4.454 -> 2.786s. All 30 phrase trials
had recorded replies, versus 28/30. E2E p95 remains over 4s. TTS and barge-in
p95 were worse in this run; WER increased by one edit. Sequential provider and
host load were uncontrolled, so the paired native comparison is the more
direct evidence of encoder-compute reduction. Do not hide slower results or
infer reliable p95 from two stop samples.

ASR <=0.8s, E2E/TTS/stop p95, meaningful response and addressee behavior, fresh
session resets, bounded long-turn stitching, configured judging, independent
larger samples and physical acoustic/Pi qualification remain unpassed. No
merge is authorized/performed by this work.
