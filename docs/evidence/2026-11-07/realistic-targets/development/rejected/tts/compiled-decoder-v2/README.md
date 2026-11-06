# Rejected decoder-only compilation probe

Both native children fully exited, and the exclusive GPU slot was released.
No production code, installed source, model, voice, weight, dtype, speed or
noise-generation code was changed. There is no implicit fallback or promotion.

The first state-capture attempt is preserved separately in
`../compiled-decoder-v1/compiled-decoder.json`. Installed MLX 0.32.4 has no public
`mx.random.state`; that explicitly guarded attempt stopped before speech
generation, with its original decoder restored. Its historical script is
`../probe_compiled_decoder_state_attempt.py`.

The root then explicitly authorized v2's public next-draw canary. After each
same-seed complete request, outside audio timing, four public uniform values
were observed. The active candidate used supported `mx.compile` on the existing
owning decoder and its unchanged array tree. It was restored after each call.

V2 made **seven native speech generations**: one baseline warmup, three
unchanged-baseline controls, one cold compiled invocation and the first
baseline/compiled warm pair. The first warm compiled call changed public PRNG
continuation, so the candidate was rejected and stopped immediately as required.
The 52-generation plan was not completed. All observations remain in
`compiled-decoder.json`; `summary.json` exposes the partial-run boundaries.

| Reached observation, complete 20-character brief text | First PCM |
| --- | --- |
| Initial baseline warmup, includes startup | 5.754546s |
| Unchanged controls | 0.180781s, 0.180161s, 0.176730s |
| Cold compiled invocation | 8.151206s |
| Warm pair, baseline | 0.193490s |
| Warm pair, compiled | 0.137432s |

Callable creation alone took 3.834 microseconds; the 8.151-second observation
includes actual first-use graph compilation and inference, not just callable
creation. There is only one warm pair; it cannot establish a p95 or useful
whole-pipeline improvement. The root reserved the sole GPU and avoided heavy
CPU/provider work. Another agent was permitted tiny fixture tests; exact overlap
with this partial probe was not logged.

All reached outputs retained 19 phonemes, 1.85 seconds of mono 24kHz PCM16 and
float32 native audio, with identical decoder input shapes/dtypes. The three
unchanged-baseline pairwise comparisons had max absolute float errors
7.82e-8–8.94e-8, RMSE 4.92e-9–5.13e-9 and 1–3 PCM samples differing by one LSB.

Cold compiled versus baseline max float error was 1.4529e-6, RMSE 1.2895e-7,
with 95 PCM samples differing by one LSB. The warm pair had essentially the
same max/RMSE errors and 99 differing PCM samples. Both strict float-byte and
PCM equality failed; no tolerance was used to hide those differences.

The cold next-draw canary matched baseline. The warm canary did not:

- Baseline SHA-256: `ee23846ba7a29bbc98388c2c5148a33149ec58bc37078d400fe8f1581717e5c6`.
- Compiled warm SHA-256: `254e46253831871eeb27eaf45ecb250ae9d006c6ce6d80dce3774dc7aae24750`.

This establishes changed observed PRNG continuation on the warm compiled path.
It does not expose complete internal RNG state. The changed-seed pair and the
remaining four texts were not reached, so frozen noise across different seeds
was not independently demonstrated. Full grapheme/phoneme coverage profiles
and the optional audit-WAV phase were also not reached; no WAVs were saved.
Those missing measurements are not counted as passes or silently substituted.

The private native report records `contract_passed: false`,
`strict_output_passed: false`, `candidate_accepted: false`,
`completed: false`, and `decoder_restored: true`, with terminal error
`Compiled warm call changed PRNG advancement`. Native child exit was 1.
No further decoder compilation is recommended from this failed candidate.
