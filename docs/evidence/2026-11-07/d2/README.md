# D2 speech verification — November 7, 2026

Implementation commits: `2fdc48e` (readiness and real self-check) and `047c4ec`
(native process watchdog and bounded output). Prior D1 remains unchanged.
The actual models, voice and cached revisions are pinned in `environment.json`.
No provider, billing or model substitution was used.

## Automated and real-model results

| Evidence type | Result | Receipt |
| --- | --- | --- |
| Baseline installed suite | 120 passed, 0 skips | `baseline.txt` |
| Readiness/audio behavior RED | 3 assertion failures and 3 errors before implementation | `readiness-red.txt` |
| Readiness GREEN/full suite | 7 focused passed; 124 total passed | `readiness-green.txt`, `readiness-suite.txt` |
| Bounded check RED/GREEN | 3 missing-feature errors, then 3 passed; 127 total passed | `check-*.txt` |
| Review lifecycle RED/GREEN | 4 failures, then 7 process tests passed | `process-red.txt`, `process-green.txt` |
| Final installed suite | **131 passed, 0 failures, 0 skips**, 5.601s | `final-suite.txt` |
| Native MLX GPU | Passed | `metal-probe.json` |
| Actual configured Kokoro | Non-silent PCM generated; 11.133s first cold attempt | `kokoro-initial.json` |
| Actual configured Whisper | Correct phrase, cold 8.106s / warm 2.789s | `whisper-initial.json` |
| Both models, same process | Correct phrase twice, cold 10.743s / warm 3.394s total | `native-warmup.json` |
| Final bounded CLI | Exact phrase recognized, 13.134s total in a fresh process | `cli-check.json` |
| Actual authenticated HTTP | 6/6 checks passed, including concurrent roles and word timestamps | `http-roundtrip.json` |
| Actual generated-input speech pipeline | Correct “That's 42.” audio; real Pipecat/VAD/SmartTurn and all three models | `pipeline.json` |
| Actual guarded service shutdown | Parent exit 0; listener no longer accepted connections | `shutdown.json` |

An intermediate focused run failed the pre-existing native-capacity test because
new startup warm-up reached unavailable SciPy in the portable test environment.
That test now explicitly supplies a no-GPU warm-up fixture while still running
a real blocked executor thread. Speech dependencies remain isolated in Python
3.12; the portable runtime does not acquire MLX/SciPy. Final full results above
include that capacity/cancellation regression.

The runtime metadata refresh initially failed because `setuptools.build_meta`
was absent from the portable environment. An isolated editable build resolved
it without changing model packages. Both environments passed `pip check`.

## Interpretation and performance limits

`voice-sample.wav` is a 2.6s synthetic Kokoro sample at 24kHz, not a microphone
recording. The final native check ran while the final regression suite was also
running; it is functional evidence, not a controlled cold-start benchmark.

Warm HTTP first-PCM samples were 0.501s and 0.290s; ASR samples were 2.786s and
2.721s. Under simultaneous ASR/TTS, first TTS PCM took 2.003s and ASR 2.934s.
These are few software-clock observations, not p95 or acoustic measurements.

The generated-input pipeline retained real inference and turn analysis, used
software PCM transport, and kept input flowing during output. Its 32.356s run
included about 22.477s from committed transcript to speech submission. Separate
Qwen calls showed first text in 26.182s and 0.233s (`foreground-latency.json`).
The cause of the variable provider wait was not identified. Slow results are
retained. No <=1s substantive-audio or <=250ms acoustic stop claim is made.

## Live checks and privacy

The operator opted into a headphone/microphone check. The 12s attempt delivered
192,000 frames but no speech/model response; the operator heard the cue and
reported missing the window (`live-check-initial.json`). A 30s open-mic retry
recognized the question's numbers and sent generated audio, but did not confirm
the expected complete answer; the operator heard another/clipped reply
(`live-check-interrupted.json`). These failures remain failures.

A single-turn retry forwarded 480,000 frames in its 30s window, but detected no
speech and made no model calls; it timed out (`live-check-single-turn.json`).
The operator reported missing that window as well. It is not counted as a
successful live turn. A subsequent diagnostic uses a manual native Start button;
the microphone is not opened while that dialog waits.

The manual-start diagnostic passed (`live-check-manual.json`): both numbers
were recognized, a complete 42 answer was produced, and the operator confirmed
it was clear and complete. The operator also reported excessive latency. ASR
took 2.898s for the partial and 2.867s for the final window. The runtime trace
shows 5.083s from VAD stop to speech submission, followed by 0.368s to first TTS
PCM. The 25.082s window-open-to-first-output field includes waiting for the
operator to speak and must not be reported as inference/response latency.
`live-check.json` contains this latest result. This single-turn success is not
natural-duplex, speaker-ownership or acoustic-p95 qualification.

Live diagnostics use explicit course preactivation and disable job actions.
They cannot qualify ownership, natural interruptions, speakerphone echo, or
benchmark behavior. A single-turn diagnostic discards new input after the first
committed turn to isolate basic speech/device function; it is not duplex evidence.
No microphone audio or user transcript is retained. Installed aiohttp uses a
1MiB in-memory upload spool, above the enforced 600,000-byte request limit;
request cleanup closes uploads (`audio-retention-contract.json`).

## Reproduce the model/service check

Use the installed environments and private local configuration from `SETUP.md`:

```sh
cd /Users/jus/Documents/Grad/AI231/ME3
./scripts/me3.sh speech --check --output .local/voice-check.wav
./scripts/me3.sh speech --host 127.0.0.1 --port 8002
```

The service only binds after a real known-phrase TTS-to-ASR warm-up passes. A
parent watchdog owns the native model process; deadlines and shutdown clean up
its process group. The isolated self-check caps stdout during reading and
rejects mismatched model IDs, failed exits, missing reports and empty audio.

The three local speech credentials in `.env` must match. They were generated
and configured privately for this checkout. Do not print or commit them.
Foreground Qwen and Pi authentication are separate and were preserved.

Run software regressions separately:

```sh
.venv313/bin/python -m unittest discover -s tests -v
.venv313/bin/python -m compileall -q me3 tests integrations
```

Independent review found and reproduced the three lifecycle/output defects;
after the fix pass it reran all 7 process tests and reported no remaining
Important/Critical findings. The external benchmark remains clean at
`106ac8e543a5fd996e254a87e69fa101bfd27a42` (`benchmark-scorer-state.json`).
No dataset scoring or Raspberry Pi qualification occurred in D2.
