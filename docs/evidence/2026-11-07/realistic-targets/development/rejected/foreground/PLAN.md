# Foreground first-sentence development pilot

Prepared only. No provider, TTS, GPU or microphone call is authorized by
preparation; the parent will grant the network slot after the benchmark.

Hypothesis: useful short complete first sentences can reduce a subsequent
whole-segment Kokoro tail. This text/provider pilot cannot prove that TTS or
acoustic improvement; the parent will measure native TTS separately.

## Comparison and bounds

The baseline prompt is captured from the actual current
`DuplexController._reply` path with fixed development history and no focused job.
The capture step supplies no semantic answer and makes no provider request.
The candidate replaces only the spoken instruction, preserving identical
conversation JSON. It says:

> Answer directly. Use short complete spoken sentences. Put the useful answer
> first. Aim for at most 12 words per sentence. Preserve numbers, qualifications
> and necessary details using additional short sentences. Do not use filler
> acknowledgements. Do not claim external actions or completed jobs.

Use the existing `ForegroundBackend` and operator-configured exact Qwen model.
Keep its thinking-disabled request, 512-token cap, exact model checks and disabled
tools unchanged. Use no third model or semantic judge. A real HTTP observer
records only model IDs, completion reasons and safe protocol flags; it never
records request URLs, headers, keys or exception messages.

Run serially. Default: eight cases, one repeat, baseline/candidate (16 calls).
Optional identical-prompt baseline control adds a third arm (24 calls). Repeats
are configurable from 1 to 5; request deadline is 30 s by default (maximum 60 s),
whole-run deadline 240 s (maximum 600 s). Counterbalance arm order with a fixed
local seed. Do not alter provider sampling parameters. Stop on auth/rate-limit
errors or three consecutive failures. Preserve partial outputs as failed records.

The fixed cases are independent development questions: arithmetic 42; water at
100 degrees Celsius plus altitude/pressure qualification; photosynthesis inputs
and products; a Tuesday-to-Thursday correction; USD 1,234.56; beginner bread
quantities; missing referents needing clarification; and an unsupported email
action that cannot be claimed complete. No benchmark labels/clips are read.

## Evidence and criteria frozen before calls

For every call retain the exact safe prompt and full output, first sentence and
actual first project `clauses()` chunk, whitespace word/character counts, all
sentence counts, first-text/first-clause/full-request times, configured/observed
model IDs, completion reasons, errors and literal guard results.

Literal guards check required facts/numbers, useful first-sentence content,
filler prefixes, stale correction text and positive external-completion claims.
They are transparent screening rules, not mocked semantic tests or a qualified
semantic scorer. Keep every failure and full answer for parent review. A fact
guard match cannot rule out negation, contradiction or a wrong explanation.

Reject promotion if any numeric/fact requirement is lost, ambiguity is guessed,
the action is falsely claimed complete, or output is empty/truncated/errored.
Review all answers even when literal guards pass. A short first sentence alone
is not a quality pass. Treat the 12-word instruction as a style aim; never repair
an overlong answer by truncation. Preserve necessary details in later sentences.

Candidate usefulness requires a lower first-sentence/first-clause size across
paired cases with quality retained. Report medians and every pair; default n=1
per case is too small for reliable provider p95 or causal timing attribution.
If enabled, baseline-vs-itself variation indicates how much observed change may
come from sampling/provider variability. Native TTS must later confirm a lower
first substantive audio delay using these unchanged full first chunks.

Whitespace counts do not estimate how numbers expand into spoken words.
Provider-only clause readiness excludes actual TTS/backpressure/playback. No
physical or course latency gate is passed by this pilot.

## Commands

Preparation is safe during the benchmark:

```sh
.venv313/bin/python .local/verification/targets/foreground/pilot.py prepare
```

After the parent grants the network slot and supplies the existing operator
environment (the runner never reads `.env` itself):

```sh
.venv313/bin/python .local/verification/targets/foreground/pilot.py run \
  --execute --repeats 1
# Optional control; no need to run both by default.
.venv313/bin/python .local/verification/targets/foreground/pilot.py run \
  --execute --repeats 2 --baseline-control
```

All artifacts stay under `.local/verification/targets/foreground/`. Production
files remain unchanged. No inference has been run while preparing this plan.
