# Decoder-only compile probe and explicit RNG protocol revision

The first `compiled-decoder-v1` native child loaded the exact model but stopped
before speech generation because installed MLX 0.32.4 has no public
`mx.random.state`. Its failure JSON and restored-decoder result are preserved.
The original planned script is `probe_compiled_decoder_state_attempt.py`.

The root explicitly authorized **v2** using a supported public-API next-draw
canary instead of unavailable RNG-state capture. The active script now compiles
only the original decoder, capturing its existing parameter array tree. It
does not wrap or replace noise generation. After each complete request, outside
the audio timing interval, it records four values from public
`mx.random.uniform`; same-seed baseline and compiled next-draw bytes must match.
Paired requests use two different seeds across repetitions, so frozen compiled
noise also appears in complete waveform error comparisons. A cold or warm
canary mismatch rejects the candidate and stops the probe immediately, retaining
all partial results and restoring the original decoder. No tolerance or
automatic promotion is introduced. The bounded v2 invocation uses output
`.local/verification/targets/tts/compiled-decoder-v2`.

The canary is evidence about the observed public PRNG continuation, not access
to complete internal RNG state or proof of every random draw. Full audio error,
duration/phoneme/source coverage, changed-seed checks and unchanged controls
remain necessary. Compiler/runtime failure also remains an explicit stop.

The rest of this note preserves the original preparation protocol; its proposed
state-capture mechanism is superseded only by the explicit v2 protocol above.

The root owns the sole GPU slot. No native imports, model loads, network calls,
weight hashing, waveform generation or service calls were used to prepare this
probe. Only small source reads, Python parsing/byte-compilation and `plan` mode
were run. Production source remains frozen at `c321634`.

`probe_compiled_decoder.py` defaults to `plan`. Its native entrypoint must not be
used before the root explicitly releases the measured-run/GPU slot.

The single candidate compiles the existing loaded Kokoro decoder with supported
`mx.compile`; it leaves the encoder, predictor, text normalization, phonemizer,
segmentation, voice loading, cache clearing and PCM conversion unchanged. The
installed `Model.__call__` itself supports a compiled decoder argument, although
normal `generate()` uses the owning model's `self.decoder`. The diagnostic keeps
the original decoder module alive, builds one compiled callable from it, and
temporarily assigns an observing callable to this loaded owner's `decoder`.
The observer delegates to either the original or compiled decoder, records only
input shapes/dtypes, and does not change arrays. `finally` restores the exact
original module after every request and on terminal failures. No installed or
project production source is edited.

Kokoro's decoder draws excitation noise. The compiler therefore captures the
original decoder's array tree and the live `mx.random.state` as inputs, and
captures RNG state as output. The probe explicitly fails if that state cannot
be captured or is replaced by seeding. Python, NumPy and MLX seeds are paired;
post-request MLX RNG state must match the same-seed baseline. Compilation is
shape-specialized (`shapeless=False`). Actual first use of each complete decoder
input-shape/dtype signature is recorded, since two texts could reuse a graph.
This avoids calling every new-text first invocation an independent cold compile.

The selected model is `mlx-community/Kokoro-82M-bf16`, snapshot
`a71e4d38b236d968966a2002c4c895dbd12b1c3c`, voice `af_heart`, speed `1.0`.
No inference or weight dtype conversion is introduced. Float64/int32 arithmetic
is used only for post-inference error measurements, without feeding it back to
the model. Loader evaluation state must already be false and remain unchanged.

The existing complete development inputs are reused verbatim: 20, 69, 77, 171
and 276 characters, including grouped decimal numbers. No shorter prefixes,
benchmark labels, filler, changed prompt or new voice/model is introduced.

The default bounded workload is **52 native generations**:

- One baseline warmup and one final restored-baseline check.
- Three same-seed unchanged-baseline controls per text: 15 generations and
  15 pairwise numerical comparisons across five texts.
- One first compiled invocation per text, with callable-creation time and
  first-shape-use metadata reported separately from warm pairs.
- Two alternating-order baseline/compiled pairs per text: ten timing pairs /
  20 generations. The second pair uses another seed to expose frozen noise.
- Separate baseline/compiled source-coverage profiles: ten generations.

The report retains complete per-request duration, PCM size, sample dtype,
phoneme count, first PCM and total timings. Coverage passes require complete
generated graphemes and exactly matching full phoneme strings. Numerical output
includes float-byte and PCM equality, max/mean/RMSE float errors, differing
sample counts and maximum PCM LSB error. Per-text min/median/max distributions
compare compiled warm output with unchanged-baseline variation. Cold errors
remain separate and still participate in strict/contract failure flags.

No tolerance or observed baseline envelope can turn a strict difference into a
pass. The candidate is never automatically accepted. Numerical differences,
RNG-state mismatch, changed shapes/dtypes/duration/phonemes, missing coverage or
failed restoration remain explicit. Saved full audit WAVs are optional via
`--save-audio`; their existence would not by itself establish speech quality.
No provider or acoustic qualification is claimed.

When authorized later, the bounded command is:

```sh
.speech-venv312/bin/python \
  .local/verification/targets/tts/probe_compiled_decoder.py native \
  --output .local/verification/targets/tts/compiled-decoder-v1 \
  --repeats 2 --controls 3 --deadline 300 --save-audio
```

HF is offline. The outer process captures library stdout/stderr to a private
log and enforces a 300-second total deadline, including model loading and cold
compilation. It kills/reaps its child process group on timeout/interruption.
Incremental JSON checkpoints preserve partial results; a compiler/runtime
exception is recorded and never triggers an implicit uncompiled fallback.
Actual support and benefit for this nested decoder are still untested.
