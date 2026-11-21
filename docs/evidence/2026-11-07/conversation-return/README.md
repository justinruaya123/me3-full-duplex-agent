# Conversation return, hesitation and listening cues — November 7

Candidate runtime: `ed6efa0dd9edaa6dceebf342392b54604bb43cbc` on
`hermes/conversation-return-v1`, based on main `2dc3554`. Subsequent commits
only publish documentation/evidence. Main retains its preceding baseline because
benchmark non-regression remains unpassed.

The implementation persists ask-first result return, offers optional notices
only after explicit committed topic wrap-ups, preserves unfinished speech with
Pipecat SmartTurn plus a finite English tail veto, and schedules guarded neutral
listening cues through the existing speaker. No new model, weights, provider,
credentials, billing setting, orchestration framework or dependency was selected.

## Separate evidence classes

- **Installed software:** [full suite](verification/full-final.log), 244 passed,
  zero failures/skips, 12.291s; [v1 subset](verification/v1-final.log), 214 passed,
  zero failures/skips, 10.515s. Red/green logs are retained. Earlier intermediate
  red full-suite logs are not final passes. Demo, compileall and E/F/I 79-column
  lint passed separately. [Review](verification/review.md) records two reproduced
  findings and their subsequent resolution. The installed Pipecat fixture test
  proves cue cancellation/fencing and retained capture, not acoustics.
- **Actual providers / trusted text / static build:**
  [33-check receipt](verification/provider-delegation.json). Pi/Sol built the
  cafe website while Qwen answered, session end left it running, reconnect stayed
  quiet, cross-owner access was denied and an explicit loopback preview returned
  HTTP 200 with the verified index hash. Node/path/viewport/hash validation does
  not establish browser rendering or responsiveness.
- **Actual speech HTTP:** [Kokoro cue receipt](verification/real-cue-smoke.json).
  One 62,400-byte cue took 0.344498s; the second call reused identical PCM in the
  same voice instance. This is not a p95, acoustic capture or natural placement
  qualification. A later [two-request provider diagnostic](verification/provider-latency-diagnostic.json)
  returned first text in 0.1354/0.0812s with TCP around 6ms; these short successes
  do not explain or reclassify the benchmark failures. Its tracing caveat is
  retained. This diagnostic is not benchmark acceptance evidence.
- **Canonical ME3:** two complete attempts below, original reports/scorer/data,
  including all failures. No custom clips, subsets, simulator, judge, UTMOS or
  revised scoring rules are substituted. The course ownership bypass is explicit.
- **Unrun:** new live-microphone natural-stutter/listening qualification,
  independent ownership, physical speakerphone/AEC, actual RPi and 30-minute soak.
  The 16-second capture limit and finite English heuristics remain limitations.

## Complete original benchmark attempts

Both attempts used canonical commit
`57eaddbc188ce9a19b8fd002b575f703426956f4`, the complete official dataset (430
manifest references checked), seed 231, ten phrases x three runs plus three
complete duplex rounds, and fresh runtime hooks for every recording including
clean twins. The original scorer used CPU-int8 `Systran/faster-whisper-small`,
without judge/UTMOS. Nine scorer file hashes and all runtime source hashes were
verified before/after. Model selections and foreground prompt stayed fixed.

| Result | Prior baseline | Attempt 1 | Attempt 2 |
| --- | --- | --- | --- |
| Run | `06-10-46` | `10-13-32` | `10-39-12` |
| Complete queue / recordings | 60 / 72 | 60 / 72 | 60 / 72 |
| Transport/scoring errors | 0 / 0 | 0 / 0 | 0 / 0 |
| E2E mean/p95 seconds | 2.552 / 3.711 (n=29) | 2.725 / 4.241 (n=29) | 3.433 / 6.702 (n=19) |
| ASR mean/p95 seconds | 1.470 / 2.036 | 1.507 / 1.965 | 1.476 / 1.924 |
| LLM mean/p95 seconds | 0.402 / 0.745 | 0.601 / 1.797 | 1.296 / 5.435 |
| TTS mean/p95 seconds | 0.424 / 0.696 | 0.402 / 0.744 | 0.405 / 0.783 |
| Stop mean/p95 seconds | 0.337 / 0.406 (n=3) | 0.252 / 0.252 (n=3) | 0.228 / 0.338 (n=4) |
| WER | 3/207 = 1.449% | 3/207 = 1.449% | 3/207 = 1.449% |
| Recorded phrase replies | 29/30 | 28/30 | 19/30 |

Both candidates fail E2E/LLM p95 gates; existing ASR/TTS gates remain open.
Do not select only the better attempt or pool correlated repeats into a new
acceptance score. Full software timing denominators can include an output mark
without detected recorded speech. Digital heard-onset mean/p95 was 3.050/4.201s
(n=28) and 3.960/7.230s (n=19), separate from physical acoustic latency.

All thirteen missing recorded phrase replies across the new attempts reached
committed ASR and foreground requests. One had output only ~97ms before close
following a 6.721s first-text wait; twelve had no first token before close.
No new hesitation veto or pre-answer cue explains those failures. Zero
pre-answer cue/output cases were found in all stage traces; these benchmark
recordings did not exercise the new listening-cue output path. Request-to-first
text includes client/network/server time; a specific provider root cause is not
established by these traces.

Pause TOR was 0/3 in each pause stratum and turn-taking TOR 1/3 in each attempt.
False-turn rates were 2/6 and 4/6. Interruption TOR was 1/2 played (three
scheduled) and 1/3. Backchannel return was 2/3 in each, with the same second-round
case not returning; content relevance/Resume remains unjudged. Only seven stop
samples were valid across twelve scheduled interruptions; missing/unplayed
cases are not zero-latency successes.

Original evidence:

- [Attempt 1 results](attempt1/me3-runs/2026-11-07_10-13-32/results.json),
  [original comparison](attempt1/verification/official-comparison.log),
  [coverage/stage audit](attempt1/verification/comparison-audit.json),
  [missed-reply traces](attempt1/verification/trace-audit.json).
- [Attempt 2 results](attempt2/me3-runs/2026-11-07_10-39-12/results.json),
  [original comparison](attempt2/verification/official-comparison.log),
  [coverage/stage audit](attempt2/verification/comparison-audit.json),
  [missed-reply traces](attempt2/verification/trace-audit.json).
- [Two-attempt denominators/provenance](two-attempt-comparison.json),
  [prior baseline](../realistic-targets/README.md).

Per-attempt manifests record exact copied bytes. The parent `sha256.json`
indexes the complete published archive excluding itself. Raw reports, CSV
padding/line endings and logs remain unchanged. No audio, dataset assets, model
weights, SQLite or auth state are included. Configured secret-value scans passed.

## Reproduce

Follow [SETUP](../../../SETUP.md) and the existing
[canonical fresh-session procedure](../../../RASPBERRY_PI_TESTING.md#use-only-the-canonical-me3-benchmark),
explicitly selecting the candidate branch. For this comparison use
`--rounds 3 --phrases 10 --runs 3 --seed 231`, the complete official corpus,
original reset/assistant hooks and original scorer. Retain all queue items,
recordings, missing stages and failures. Do not run the Mac MLX installer on Pi.
The provider scripts are separately labelled probes, not replacements for ME3
acceptance. Run them from the project root after loading the ignored operator
environment. The delegation script expects its original private directory
layout: copy it without overwriting an existing file to
`.local/verification/conversation-return/provider-delegation-smoke.py`, then use
`PYTHONPATH=. .venv313/bin/python .local/verification/conversation-return/provider-delegation-smoke.py`.
The cue script uses the current project directory. Keep keys out of commands,
chat and commits.

Next unpassed gate is repeatable E2E/LLM timing and recorded-reply coverage with
the selected foreground endpoint; ASR/TTS, semantic ownership/turn handling,
physical acoustics and target Pi validation remain open. Functional tests and
provider/static-build checks pass; the benchmark is not claimed improved.
