# VAD development evidence and empty-turn pause resolution

This folder contains actual installed CPU Silero detector measurements and
fixture-only Pipecat pause tests. It contains no microphone recording, acoustic
playback measurement, ASR/provider benchmark, speaker-verifier qualification or
held-out course scoring. After the empty-turn fix was committed, the parent
authorized applying the development VAD candidate with a separate RED/GREEN
pipeline regression. That change is ready for parent review/full-suite checking.

## Frozen detector experiment

`PROTOCOL.md` and the eight setting rows in `measure_vad.py` were written before
running the grid. The positive corpus is the private working D2 sample plus
eight new exact Kokoro/af_heart utterances generated independently of the course
clips. `development-speech/receipt.json` records the parent-generated sources.
All nine are one synthetic voice; gains/prefix conditions are correlated
perturbations, not 135 independent human observations.

Each source gets fixed 0/-6/-12/-18/-24 dB gain and warm-silence, immediate-stream
or 20 dB SNR seeded white-noise conditions: **135 speech trials per setting**.
The source onset/end references are the first/last 10 ms source-energy bins above
-50 dBFS RMS before applying gain. A detected start after the last such bin is
counted as late. These are digital conventions, not human onset labels.

Each setting also sees the same **11 negative streams / 66 seconds**: silence,
three white-noise levels, two pink-noise levels, isolated click, click train,
40 ms noise bursts, 440 Hz tone and harmonic hum. Replaying those negatives
under eight settings does not provide eight times the independent exposure.

Pipecat `1.15.1.dev12` uses actual ONNX CPUExecutionProvider, mono PCM16/16kHz,
and 20 ms input chunks. Its model receives 32 ms windows. The reported latency
uses consumed-audio sample time; CPU service time is separately recorded.
`development-grid/measurements.json` includes full records, software/model
hashes and source hashes; `window-traces.json` contains real confidence and
volume observations. The full run took 54.978 s wall time while other host work
was active. Do not use its CPU service times as quiet-host latency qualification.

| Setting (confidence / start / min volume) | Before-end detections | Late / absent | Detected-only median / p95 / max |
| --- | --- | --- | --- |
| Baseline .7 / .200 / .6 | 123/135 | 7 / 5 | 420 / 1081 / 1420 ms |
| .7 / .128 / .6 | 128/135 | 3 / 4 | 370 / 693 / 1330 ms |
| .7 / .096 / .6 | 131/135 | 2 / 2 | 330 / 660 / 1290 ms |
| .7 / .064 / .6 | 132/135 | 2 / 1 | 310 / 629 / 1270 ms |
| .6 / .096 / .6 | 131/135 | 2 / 2 | 330 / 660 / 1290 ms |
| .7 / .096 / .5 | 135/135 | 0 / 0 | 260 / 393 / 430 ms |
| .6 / .096 / .5 | 135/135 | 0 / 0 | 260 / 393 / 430 ms |
| Diagnostic .7 / .096 / 0 | 135/135 | 0 / 0 | 160 / 250 / 360 ms |

P95 values exclude late/absent starts, so they cannot hide those misses. The
baseline has more than 5% before-end misses and has not established a complete
onset p95. Several late starts are only 10–30 ms after the coarse energy end;
this boundary is not an ASR error or a course score.

Every setting had **0 starts / 11 artificial negative streams / 66 s** and no
pre-speech starts in the positive trials. This narrow set does not distinguish
their false-onset risks. If these were homogeneous random Poisson exposure,
zero events would still allow a one-sided 95% upper bound about 2.72 events/min;
the deterministic synthetic set does not justify that population assumption.
No TV, bystander speech, competing voices, music, laughter, reverberation,
physical echo, double-talk or diverse human speakers were tested.

## What causes the delay

The installed analyzer requires both Silero confidence and smoothed volume.
Volume uses a 400 ms BS.1770 rolling window and exponential smoothing with
factor .2. Fresh streams have volume 0 until enough PCM exists. Warm silence
fills the window, but the volume still ramps after speech starts. A nominal
`.200` start rounds to six 32 ms windows; `.128` to four; `.096` to three;
`.064` to two. Input-chunk reporting can add up to another 20 ms quantization.

In D2 nominal warm speech, confidence crosses .7 at 70 ms after the defined
onset, smoothed volume crosses .6 at 198 ms, and baseline start is 370 ms.
Changing start alone to .096 gives 270 ms; min volume .5 plus .096 gives 230 ms.
At -24 dB (D2 active RMS about -49.45 dBFS), confidence crosses at 102 ms but
volume reaches .6 only at 518 ms, just as confidence drops during a word gap.
That resets the required run, and baseline start is 1130 ms. Lowering confidence
to .6 does not fix this. At min volume .5, its first crossing is 326 ms and the
same clip starts at 390 ms. Removing volume entirely is diagnostic, not an
endorsed production change.

`trace-validation.json` compares the instrumentation with the unmodified
installed analyzer for four representative gain/setting pairs: all 218 chunk
states matched in each pair. This checks measurement instrumentation, not
speaker or acoustic accuracy.

## Applied development candidate; further qualification remains open

Keep confidence .7 and stop .2. The modest candidate is start **.096** and min
volume **.5**, retaining a three-window onset requirement. It removes quiet
speech misses in this development corpus without the unsupported step of
removing the volume gate. Lowering confidence has no measured benefit here.
The 64 ms run adds little median benefit and provides less evidence persistence.

Use approximately **400 ms as a provisional digital detector development
budget**, with the observed 430 ms maximum retained as a failure against a
strict 400 ms ceiling. This is neither a promised playback stop nor the spec's
250 ms acoustic target. The saved benchmark output-stop delay cannot simply be
added to these different samples to claim a measured end-to-end improvement.
Freeze a candidate before any new held-out scoring and keep all failed trials.

A more sensitive onset also pauses more short acknowledgments before ASR can
classify them. Faster yielding can therefore lengthen unnecessary audible gaps
while the current segment ASR is slow. Preserve unplayed PCM, bound all queues,
keep capture live, and require the original SmartTurn/revision/owner/addressee
gates for every nonempty commit. VAD cannot authorize cancellation, foreground
requests or jobs. Fast onset is not evidence of backchannel/addressee quality.

Before promoting the candidate, add diverse independent development negatives
with TV/speech/echo and physical double-talk, verify noise/empty pause resolution,
then measure actual playback onset-to-stop and interruption relevance at the
transport and acoustic boundaries. Full course and target-hardware gates remain
unpassed.

The parent subsequently authorized this candidate as the default provisional
pause configuration, without changing transcript/owner authorization. It remains
unqualified for physical echo and speech-noise. `tests/test_vad_onset_v1.py`
exercises the actual project build, installed CPU detector and bridge. It does
not inspect parameter getters or construct a replacement detector. It feeds the
D2 development phrase at -24 dB with 750 ms warm silence and requires onset
within 450 ms after the frozen digital energy reference. A separate 6 s stream
combines seeded -30 dBFS white noise and loud clicks and requires no provisional
turn. Fixture methods raise if ASR, SmartTurn, TTS, foreground or jobs are invoked.
Inference and action permission are therefore not inferred from the onset.

Observed RED before the parameter edit: **2 tests, 1 pass, 1 failure**, no onset
within 450 ms (`project-onset-red.txt`). After applying only explicit
`VADParams(confidence=.7, start_secs=.096, stop_secs=.2, min_volume=.5)` in the
pipeline: **2/2 passed, zero failures/skips**, 1.997 s
(`project-onset-green.txt`). These first receipts used the private working D2
copy. D2 was used in development and is not a held-out validation sample. This
additional deterministic 6 s stream does not establish a population false
interruption rate or turn the prior 66 s into independent speech-noise evidence.

The final regression now uses committed
`docs/evidence/2026-11-07/d2/voice-sample.wav`, with no missing-fixture skip.
Missing repository data therefore fails the check; only the optional Pipecat
dependency retains an explicit skip. The public and working copies have the
same 24 kHz mono PCM16 format and 62,400 frames, but their file and PCM hashes
differ. The public file SHA256 is
`8ae222355a5c941aa7e26455aa4c8ba9a8bf4f6d61ae5cfbd9c6c45849c25d46`;
the private grid source is
`5acd95a2daa09061acbc47ab0efdcc26fd35c8439357f1a85fdb3df68eb820dc`.
`public-fixture-comparison.json` records 43,911 differing samples and maximum
PCM16 difference 1,894. The original 135-variant grid is not relabeled as public
fixture data.

After the path correction, controlled baseline replay through the actual
project pipeline and installed CPU detector again produced **2 tests, 1 pass,
1 failure, zero skips**, 1.944 s (`public-project-onset-red.txt`). The noise
stream passed; quiet speech did not begin within 450 ms. The replay script
replaces only constructor parameters in its own process with actual installed
VAD defaults and never edits production files. The current candidate then
passed the normal test invocation using the public fixture: **2/2 passed,
zero failures/errors/skips**, 1.964 s (`public-project-onset-green.txt`).

## Empty-recognition regression and minimal fix

`test_provisional_pause.py` first reproduced a project liveness defect with real
installed Pipecat processors and fixture inference. A VAD onset paused retained
PCM, but empty final ASR emitted no event to release that pause. Initial result:
**3 tests, 2 pass, 1 expected failure**, preserved in `pause-boundary-red.txt`.

The promoted `tests/test_provisional_pause_v1.py` reproduced the same RED before
production edits (`project-pause-red.txt`). Capture contract tests then recorded
the absent callback interface (`project-capture-contract-red.txt`). A separate
malformed-result RED (`malformed-red.txt`) prevented treating provider None as
an empty speech result.

The authorized fix changes only `me3/capture.py`, `me3/audio_pipeline.py` and the
new focused test file. A final empty turn with no nonempty provisional history
is retired with a new generation, fencing older queued snapshots. Its optional
synchronous `on_empty(generation)` notification is separate from transcript
commits. The bridge rechecks generation, active speech, mute and close before
resuming retained PCM; no await separates that check from resumption. Nonempty
incomplete turns remain held. Provider errors/timeouts remain explicit; malformed
recognition raises TypeError. Deferred finalization carries its VAD-stop
generation so an old stop cannot mark new speech inactive.

Focused installed verification: **11/11 passed, zero failures/skips** in 0.799 s
(`project-pause-green.txt`); existing capture regressions **8/8 passed**, zero
failures/skips (`capture-existing-green.txt`). These include byte-identical
backchannel resumption without epoch change; no action from provisional stop;
empty-final resolution; no-PCM resolution; late empty results after new speech
or close; old queued stop; prior incomplete text; and explicit provider failure.

The already-started broader restricted v1 run is **not GREEN**: it ran **134
tests in 43.448 s, 10 failures, 10 errors**, with socket/bind PermissionError and
dependent benchmark-control fixture timeouts. Preserve `v1-suite-green.txt` as a
failed restricted receipt despite its historical filename. Do not infer a pass
count by subtracting subtest failures. The parent owns the complete installed
suite with local socket capability and the final status/commit update.

Reproduce the detector grid without model/provider/microphone calls:

```sh
.venv313/bin/python .local/verification/targets/vad/measure_vad.py \
  --extra-dir .local/verification/targets/vad/development-speech \
  --output .local/verification/targets/vad/development-grid
.venv313/bin/python .local/verification/targets/vad/validate_trace.py
LOGURU_LEVEL=WARNING .venv313/bin/python -m unittest discover -s tests \
  -p 'test_provisional_pause_v1.py' -v
```
