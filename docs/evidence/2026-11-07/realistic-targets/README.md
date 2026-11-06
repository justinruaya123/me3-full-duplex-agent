# Canonical ME3 validation and separate development evidence

November 7, 2026, published branch `hermes/benchmark-latency-v1`.
The final measured runtime is `6bbbfd57d5e5c062ec3846762158118a7318b0db`.
Only the unchanged canonical ME3 benchmark, complete official dataset and
original scorer are used for benchmark acceptance evidence. Native profiles,
control/transport tests and provider prompt pilots below remain separate
forms of development evidence. Rejected candidates remain rejected.

## Final canonical ME3 results

[Official results JSON](me3-runs/2026-11-07_06-10-46/results.json),
[original HTML report](me3-runs/2026-11-07_06-10-46/results.html),
[original CSV](me3-runs/2026-11-07_06-10-46/results.csv),
[session](me3-runs/2026-11-07_06-10-46/session.json),
[queue](me3-runs/2026-11-07_06-10-46/queue.json),
[score log](me3-runs/2026-11-07_06-10-46/score.log) and
[run metadata](me3-runs/2026-11-07_06-10-46/wrapper/run-metadata.json)
retain the external outputs unchanged.

Canonical ME3 `57eaddbc188ce9a19b8fd002b575f703426956f4`, seed 231,
ten phrases repeated three times and three complete duplex rounds completed
**60/60 queue items / 72 recordings** in **1357.089s**, with zero transport or
scoring errors. Every recording, including clean twins, uses a fresh owned
runtime through the official hooks; course ownership bypass is global.

| Official metric | Mean | p95 | Target | n |
| --- | --- | --- | --- | --- |
| E2E, VAD end to software output mark | 2.552s | 3.711s | 4.0s | 29 |
| ASR final | 1.470s | 2.036s | 0.8s | 30 |
| LLM first text | 0.402s | 0.745s | 1.5s | 29 |
| TTS first PCM | 0.424s | 0.696s | 0.6s | 29 |
| Interruption stop | 0.337s | 0.406s | 0.8s | 3 |
| WER | 3/207 = 1.449% | Not applicable | 15% | 30 |

The target applies to both mean and p95. There are **29/30 recorded phrase
replies**. One trial has an ASR-final and LLM-request mark but no observed first
text/output before its 10.912s recording closes; its final mark is at 3.9993s.
The cause is not established by this telemetry. The upstream scorer excludes
that missing stage timing; it is not a pass or proof of a complete-service SLA.
The largest retained E2E/LLM observations are 6.304s/4.609s. Digital recorded
speech onset is a different clock: **3.066/4.158s**, n=29, not acoustic capture.

There were six scheduled interruption cases but three valid stop measurements;
already-silent cases are retained rather than assigned zero latency. The
sampled stop result does not establish a reliable p95 or physical 250ms target.
Turn-taking TOR is 1/3; interruption TOR 2/3; pause TOR 0/3 in each pause stratum.
The original false-turn metric is 2/6 under its word threshold, while **4/6
false-turn recordings contain detected bot speech**, including short replies
below that threshold. Independent addressee rejection is not qualified.
Backchannels returned in 2/3 cases and one did not. The known first-round
acknowledgement returned after 1.832s while remaining provisional; this does
not generalize to every acknowledgement or certify content preservation.
No judge/UTMOS was configured; Respond/Resume/content/MOS remain unscored.

[Independent final audit](audit.md) and [coordinator verification](verification.json)
record the final checks. [Operator acceptance analysis](acceptance.json) records these limitations
without replacing the original scorer. [Pins](pins.json) verifies all nine
scorer hashes and the official dataset-manifest hash against the earlier pin,
a clean external checkout, and current runtime/test code equal to the measured
commit. The fixed report title is an upstream template; the actual measured
machine is Darwin/16GB. Pi hardware was not tested.

## First fresh-session run, preserved separately

[Original report](me3-runs/2026-11-07_05-16-13/results.json) at `c321634`
completed 40/40 items / 44 recordings in 802.706s. Mean/p95: E2E 3.287/6.140s,
ASR 1.462/1.958s, LLM 1.017/3.307s, TTS 0.465/1.128s, stop 0.316/0.345s
(n=2); WER 3/207=1.449%, 29/30 recorded phrase replies. The final run retains
its three-round protocol and these earlier observations separately. Provider
load and reply variation prevent attributing LLM/TTS differences to code.

The first run may overlap the reset-transport test's 05:16:18–05:16:20.1 Manila
window and model hashing/archive I/O that had completed by 05:17:37.535. Exact
hash start/end was not captured. Potentially affected trials are retained. No
extra profiles, provider pilots, model hashing or bulk archive work ran during
the final recording; the final full suite and scoring ran after it closed.

Both run packages preserve original per-trial timing, available stages/stats,
launcher and runtime-event logs. Final source has 72 timing files and **71 stage
files**: `r02_false_tt_false_noise_009` has no stage file in the source, so none
was synthesized. First source has 44 timing and 44 stage files. All 116 runtime
logs and launcher logs are retained. Historical control-state `ready:true`
bytes are unchanged; separate cleanup observations record removed sockets and
absent final child PIDs/groups:
[final cleanup](me3-runs/2026-11-07_06-10-46/wrapper/cleanup-observation.json),
[first cleanup](me3-runs/2026-11-07_05-16-13/wrapper/cleanup-observation.json).

## Verification and rejected candidates

- [Final complete installed suite](full-suite/final.txt): **208 passed,
  zero failures/skips**, 14.958s; [v1 subset](full-suite/paused-backchannel-v1.txt):
  **178 passed, zero skips**, 10.532s. [Demo](full-suite/final-demo.txt) is labelled
  control simulation. Compilation and source lint are separate checks.
- [Floor review RED](floor/paused-backchannel-review-red.txt) has 26 tests and
  four reproduced failures; [GREEN](floor/paused-backchannel-review-green.txt)
  passes 26/26, including five installed-Pipecat scheduling fixtures with fixture
  inference. [Independent source review](review.md) explains the first-PCM and
  question-lifetime fixes and provisional action restrictions.
- [Current provider smoke](service/current-provider-smoke.json): real Qwen and
  Sol inference plus local Pi RPC pass. Overall normal-voice readiness remains
  false for missing wake phrase and independent speaker/overlap/addressee service.
  [Speech readiness](service/final-source-readiness.json) is actual model warmup
  and authenticated catalog validation, not acoustic or ownership qualification.
- [TTS compiler v2](development/rejected/tts/compiled-decoder-v2/README.md):
  seven generations, 8.151s cold call, changed warm PRNG continuation; stopped,
  original decoder restored, candidate rejected. Unreached tests are not passes.
  The [earlier state-capture failure](development/rejected/tts/compiled-decoder-v1/compiled-decoder.json)
  remains a failure before speech generation.
- [Foreground V1](development/rejected/foreground/run-20261106T213440560521Z/summary.json)
  completes 24 real Qwen calls but fails clarification. [V2 rejection](development/rejected/foreground/v2/REJECTED.md)
  retains 30 protocol-complete calls with incorrect causal explanation/incomplete
  clarification. Literal matches do not certify meaning. No prompt was promoted.

**Next unpassed gate:** ASR final <=0.8s with Turbo fixed; current warm ordinary
native inference is about 0.98s before queue delay. TTS p95 <=0.6s, broader
semantic/ownership behavior, busy-worker audio, long dictation, content/MOS,
physical acoustics/AEC, actual Pi installation/device tests and the 30-minute
soak also remain unpassed. [Setup](../../../SETUP.md),
[canonical methods](../../../BENCHMARK.md) and
[planned Pi procedure](../../../RASPBERRY_PI_TESTING.md) give the reproduction
paths. No alternate subset was benchmarked or credited as acceptance evidence.

The initial native appendix comprised 64 byte-preserved files; later canonical,
review and rejected-experiment packages were added without changing source
report bytes. The exact inventory is [sha256.json](sha256.json), excluding the
manifest itself. No raw audio, datasets, weights, operator environment/auth files
or unrelated workspace files are included. Historical native scripts retain
original private path assumptions; their archive location is not a runnable
replacement for those paths. The source root for those reports was
`/Users/jus/Documents/Grad/AI231/ME3/.local/verification/targets/`.

## Selected models and recorded hashes

Whisper Turbo remains a hard constraint. No smaller checkpoint, forced-English
production profile, new voice, synthesis speed change or model fallback was
introduced. The native speech environment was Python 3.12.13, MLX 0.32.4,
MLX Whisper 0.4.3, MLX Audio 0.6.4 and Misaki 0.9.4. TTS uses `af_heart`,
speed 1.0 and mono PCM16 at 24 kHz; ASR input is mono 16 kHz.

| Selection | Local snapshot revision | File whose content was hashed |
| --- | --- | --- |
| `mlx-community/whisper-large-v3-turbo` | `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` | `weights.safetensors`, 1,613,977,612 bytes |
| `mlx-community/Kokoro-82M-bf16` | `a71e4d38b236d968966a2002c4c895dbd12b1c3c` | `kokoro-v1_0.safetensors`, 327,115,152 bytes |
| Kokoro `af_heart` | Same Kokoro snapshot | `voices/af_heart.safetensors`, 522,320 bytes |

Content SHA-256 values computed from the local files during archive preparation:

- Whisper weights: `951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6`.
- Kokoro weights: `4e9ecdf03b8b6cf906070390237feda473dc13327cb8d56a43deaa374c02acd8`.
- `af_heart`: `2c1c733b0e6576c810e268d3e440c21dea4e0f0131a3ba4cfc98d7fe6136d094`.
- The measured Silero ONNX file: `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.

The first three are actual file-content hashes, not cache-blob identifiers from
older cache-inventory notes. The TTS report independently records the loaded
snapshot, voice hash and native method-source hashes. Detector source/model and
all input-source hashes are in the grid's `source_hashes` and `speech_sources`
fields. Remote foreground/worker inference was not measured by these native
probes; their provider-managed weights are not covered by these file hashes.

## ASR: guarded automatic-language feature reuse

The production change computes the exact installed first decoder mel window,
including the full 30-second model context. Requests remain bounded to 16 seconds
of captured mono audio. The original complete waveform still reaches normal
transcription with word timestamps. A request-local one-entry memo keys the
complete mel shape, dtype and bytes; changed windows re-encode, and every exit
restores the encoder and clears the memo.

Automatic detection first uses the shared decoder features. At maximum language
probability **at least 0.95**, that detected language is used. Below 0.95, the
original installed language-detection mel is encoded separately and its result
is selected, retaining the decode memo. This changes the language detector's
padding on the confident path. The threshold is a development heuristic, not
a calibrated correctness guarantee or proof of equivalence to standard
detection. It neither assumes English nor grants ownership or turn authority.
No universal language, transcription or quality parity is claimed.

| Evidence | Interpretation |
| --- | --- |
| [Encoder policy RED](asr/encoder-policy-red.json) | Before the production change, ordinary inputs needed two encoder calls; the intended one-call condition failed. |
| [Encoder policy GREEN](asr/encoder-policy-green.json) | Three paired generated inputs retained text, language and every word field; project calls were 1, 1 and 2 for the two ordinary and one ambiguous input. |
| [Twenty-pair qualification](asr/encoder-policy-quality.json) | Ten development inputs, two repetitions, alternating reference/project order: all **20/20 pairs** have identical text, language and every returned word field. All 40 raw timings remain. |
| [Language distributions](asr/language-native.json) | Standard versus decoder-mel detection on generated development speech; supports the ambiguity analysis, not multilingual accuracy. |
| [Language-policy RED](asr/language-policy-red.txt), [GREEN](asr/language-policy-green.txt) | The initial four tests failed before the helper existed; the expanded helper/cache suite passed **7/7**, zero skips. These are CPU policy/cache tests, not native evidence by themselves. |

The qualification contains 18 ordinary pairs and two low-confidence ambiguous
pairs. Excluding **only the initial `ready-r1` pair** from the ordinary warm
summary leaves **17 warm ordinary pairs**: reference mean **1.823815s**, project
mean **0.977800s**. The initial pair is retained in the raw file and is excluded
only from that explicitly labelled warm summary. The two ambiguous pairs are
reported separately: **1.807484s → 1.820970s** and
**1.822068s → 1.844114s**, with two project encoder calls each.

The ambiguous generated “Mm-hmm” input retained the reference's Swedish
`Mämmel.` result after the conservative fallback. Equality to that result is
not evidence of a correct transcript or correct language. The final selected
path preserved the measured reference outputs; it did not repair the reference
model's recognition errors. Diverse human speech, accents, multilingual/noisy
inputs and independent quality evaluation remain open.

Rejected and diagnostic attempts are preserved:

- [Fused attention probe](asr/attention-probe.json): the report's `passed: true`
  uses a phrase/nonempty-word smoke criterion. Fused output changed a returned
  word probability and did not establish a useful exact-output improvement.
  Fused attention was not promoted.
- [Unguarded single/compiled experiment](asr/single-native.json): `passed: false`;
  the initial reuse approach changed the ambiguous input's language/transcript.
  The later guard must not be retroactively credited to that failed candidate.
- [Compilation wrapper rejection](asr/compile-probe.json) and
  [single-probe wrapper rejection](asr/single-probe.json) preserve
  `InvalidReportError`. That wrapper result is not a native pass and does not
  distinguish malformed framing from a reported failure. The direct
  `single-native.json` report is valid JSON with a failed quality condition;
  the compile attempt's precise report-rejection cause was not recovered.

## TTS: full-segment cost and rejected scalar candidates

[Full native report](tts/native-v1/native.json),
[unchanged-baseline controls](tts/native-v1/determinism.json) and
[compact summary](tts/native-v1/summary.json) retain all outcomes. There were
30 pairs / 60 paired generations, five stage profiles, one line profile and one
warmup. Follow-up controls used ten unchanged-baseline generations, two RNG
profiles and one warmup: **80 native synthetic-speech generations total**.
The main profiler exited nonzero because its strict equality gate failed.

| Complete input | Phonemes | First native PCM | Forward including evaluation |
| --- | --- | --- | --- |
| 20 characters | 19 | 0.1891s | 0.1851s |
| 69 characters | 67 | 0.3895s | 0.3798s |
| 77 characters with numbers | 127 | 0.6490s | 0.6380s |
| 171 characters | 169 | 0.8434s | 0.8248s |
| 276 characters | 270 | 1.3589s | 1.3232s |

All five profiles retained complete source graphemes and all 30 pairs retained
phoneme counts. First native PCM waits for the complete current synthesis
segment. Numeric expansion makes character count a weak latency predictor.
Voice loading was under 0.4ms and G2P under 4ms in these profiles. Stage durations
are inclusive and must not be added to one another; the line trace perturbs
execution and was excluded from paired timing.

Bulk duration reads, retained exact voice tensors and bulk timestamp reads had
ten pairs each. Their median paired first-PCM changes were **−3.55ms, +0.08ms
and −0.83ms** respectively. The duration candidate's −22ms mean was influenced
by slower baseline observations. No scalar/cache candidate was promoted.

Exact float and PCM equality failed in all 30 candidate pairs and also in
**5/5 unchanged-baseline controls** after resetting MLX, NumPy and Python RNGs.
All modules stayed in evaluation mode; instrumented excitation RNG draws
matched. Unchanged-path maximum absolute float differences were about 1e−7,
with RMSE about 5e−9. Saved candidate/profile-baseline WAV comparisons had equal
lengths and 1–24 samples differing by one PCM16 unit. The precise varying
operation was not isolated. Those observations do not convert failed bitwise
checks into passes or establish pronunciation quality. WAVs remain private and
are not part of this archive.

[Investigation notes](tts/investigation-notes.md) preserve the detailed method.
[Clause notes](tts/clauses-summary.md) describe the separate project-owned fix:
token partitions cannot split decimals, version/date spans, titles or source
words; confirmed boundaries retain backpressure, and indivisible over-limit
tokens fail explicitly. [Initial RED](tts/clauses-red.txt),
[original-function regression](tts/clauses-original-regression.txt),
[14-test GREEN](tts/clauses-green.txt) and
[18-test control GREEN](tts/clauses-duplex-green.txt) are preserved. The final
14-test suite produced 212 failing assertions against the original function.
No natural comma/colon behavior was added in this iteration.

## VAD: installed CPU detector and provisional-pause safeguards

[Frozen protocol](vad/PROTOCOL.md), [detailed notes](vad/README.md),
[full development grid](vad/development-grid/measurements.json) and
[window observations](vad/development-grid/window-traces.json) cover the real
installed Silero/ONNX CPU analyzer, including smoothed volume. The environment
was Pipecat 1.15.1.dev12, ONNX Runtime 1.31.1, Python 3.13.6 and 20ms 16kHz
mono PCM16 input chunks. The model receives 32ms windows. Latency is measured
on consumed-audio sample time; CPU service time is separate.

There are nine synthetic single-voice sources, fixed gains and prefix/noise
conditions: **135 correlated speech trials per setting** across eight settings.
Each setting replays the same **11 artificial negative streams / 66 seconds**.
The [generation receipt](vad/development-speech/receipt.json) retains the eight
new development texts. These are not independent human observations, diverse
speech-noise exposure or held-out benchmark trials.

The baseline `.7 / .200 / .6` had **123/135 before-end detections**, seven late
starts and five absent starts; detected-only p50/p95 were **420/1081ms**. The
selected `.7 / .096 / .5` candidate had **135/135**, with **260/393ms** p50/p95
and **430ms maximum**. Confidence remains .7 and stop remains .2. Every setting
had zero starts on the same 66 seconds of artificial negatives; that exposure
does not qualify TV, bystanders, echo, music, double-talk or a population false
interruption rate. The 430ms observation also remains a failure against a strict
400ms provisional development budget. No 250ms acoustic stop claim is made.

[Trace validation](vad/trace-validation.json) matched all 218 chunk states in
each of four selected replays against the unmodified analyzer. The earlier
[single-source measurements](vad/d2-initial/measurements.json) and
[traces](vad/d2-initial/window-traces.json) remain labelled as that earlier
development subset.

The grid used the private working D2 sample, file SHA-256
`5acd95a2daa09061acbc47ab0efdcc26fd35c8439357f1a85fdb3df68eb820dc`.
The committed D2 sample used by the final regression has SHA-256
`8ae222355a5c941aa7e26455aa4c8ba9a8bf4f6d61ae5cfbd9c6c45849c25d46`.
They have the same format/frame count but different audio;
[the comparison](vad/public-fixture-comparison.json) records 43,911 differing
samples. Do not relabel the grid as public-fixture data or substitute one WAV
for the other when claiming reproduction.

The public-fixture [baseline replay RED](vad/public-project-onset-red.txt)
was one pass / one failure; the [candidate GREEN](vad/public-project-onset-green.txt)
passed **2/2**, zero skips. These exercise the project bridge and installed CPU
detector; the separate six-second noise stream requires no provisional turn.
Inference, turn completion and actions do not follow from this onset evidence.

Empty recognition previously left playback paused. Its
[boundary RED](vad/pause-boundary-red.txt),
[project RED](vad/project-pause-red.txt),
[capture contract RED](vad/project-capture-contract-red.txt) and
[malformed-result RED](vad/malformed-red.txt) retain distinct failures.
[Project GREEN](vad/project-pause-green.txt) passed **11/11** and
[existing capture checks](vad/capture-existing-green.txt) passed **8/8**.
Current-generation empty resolution resumes retained PCM without authorizing
a nonempty turn, while mute/close/new speech/stale generations remain fenced.
The original private-fixture [onset RED](vad/project-onset-red.txt) and
[GREEN](vad/project-onset-green.txt) are also retained.

**The historical filename [vad/v1-suite-green.txt](vad/v1-suite-green.txt) is a
failed restricted run:** 134 tests, 10 failures and 10 errors, 43.448s, including
denied socket binds and dependent fixture timeouts. Its bytes and misleading
historical filename are preserved. It must not be counted as a successful suite.

## Installed control, transport and service receipts

| Receipt | Scope and observed outcome |
| --- | --- |
| [Full installed suite](full-suite/inference-turns-clauses.txt) | **182/182**, zero failures/errors/skips, 10.918s. |
| [v1 subset](full-suite/inference-turns-clauses-v1.txt) | **152/152**, zero failures/errors/skips, 9.177s; this is a subset, not 152 additional independent tests. |
| [Earlier full stage](full-suite/pre-inference.txt), [earlier v1 stage](full-suite/pre-inference-v1.txt) | **167/167** and **137/137**, zero skips, before the later inference/clause/onset increments. |
| [Current-stage demo](full-suite/demo-inference-turns-clauses.txt), [earlier demo](full-suite/demo-pre-inference.txt) | Explicit control simulations with fixture inference; no provider or acoustic claim. |
| [Fresh-control GREEN](wrapper/fresh-control-green.txt) | **15/15**, zero skips, ResourceWarnings treated as errors; real local sockets and owned fixture child processes. |
| [Timeout RED](wrapper/fresh-control-timeout-red.txt), [message-deadline RED](wrapper/fresh-control-deadline-red.txt) | Preserve timeout validation and slow-request failure evidence. |
| [Guarded service readiness](service/readiness.json) | Actual startup and authenticated exact-model catalog, 9.865s; not a benchmark result. |
| [Authenticated HTTP check](http/http-roundtrip.json) | **6/6 checks**, including exact catalog/model rejection, generated speech round trips, word timestamps and concurrent ASR/TTS. The concurrent TTS first-PCM observation is 1.203s and remains visible. |

[Wrapper design/verification notes](wrapper/fresh-session-control.md) explain
the separate trusted benchmark process control. It does not change ordinary
voice-session job lifetime. TERM/INT/reset/disconnect cleanup is bounded;
abrupt SIGKILL cannot run cleanup and has no claimed orphan-recovery guarantee.
Those 15 focused wrapper checks are fixture transport/control tests. The
completed canonical provider runs above supply separate end-to-end reset
evidence; the transport-only probe under `transport-reset/` omitted the clock
and sent no input audio, so it is not a benchmark or model-inference pass.

## Historical scripts and archive timing

The archived Python files are historical experiment sources. They are not
installed entrypoints or a claim that the experiments run from their copied
locations. ASR scripts originally lived under
`.local/verification/targets/asr/`; their `Path(__file__).parents[4]` assumptions
refer to that original repository depth. VAD scripts originally lived under
`.local/verification/targets/vad/` and use the original working WAV/report paths.
The TTS pair of scripts originally lived together under
`.local/verification/targets/tts/`, where the parent directory determined their
private output root. The HTTP script originally lived under
`.local/verification/targets/http/`. Existing inherited operator environment,
optional installed dependencies and original inputs were required. Copying a
script does not bundle those assets or authorize a provider/model call.

- ASR sources: [attention](asr/probe_attention.py),
  [compilation](asr/probe_compiled.py), [single encode](asr/probe_single_encode.py),
  [language distributions](asr/probe_language.py),
  [policy RED/GREEN](asr/check_encoder_policy.py),
  [twenty-pair qualification](asr/qualify_encoder_policy.py).
- TTS sources: [bounded profiler](tts/profile_tts.py),
  [unchanged-baseline controls](tts/check_determinism.py).
- VAD sources: [grid measurement](vad/measure_vad.py),
  [instrumentation validation](vad/validate_trace.py),
  [baseline project replay](vad/replay_default_vad.py),
  [initial pause reproduction](vad/test_provisional_pause.py).
- HTTP source: [generated round-trip check](http/verify_http.py).

No duplicate `quality-runner.json`/`language-probe.json` aliases or mutable
progress reports were needed; the complete final qualification and language
reports are retained. No failed observations were removed from those selected
reports. Final report provenance is pinned above and the manifest inventories
the published bytes.

Archive preparation included read-only local model hashing followed by copying.
The private byte-copy check was written at **2026-11-06 21:17:37.535 UTC /
November 7 05:17:37.535 Manila**; hashing had completed before copying started.
The hashing process did not record an exact start/end wall-clock interval, so
that timestamp is an upper bound for all preparation hashing/copy I/O, not an
exact hash completion time. A subsequent measured run began its first trial at
05:16:19 Manila. Its reports above preserve and label that possible overlap;
no affected observation was removed. The native development timings
above come from the earlier recorded experiments, not from archive creation.
