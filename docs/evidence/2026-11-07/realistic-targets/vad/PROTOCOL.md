# Provisional VAD onset development protocol

Written before running the candidate grid. This is a CPU detector experiment,
not a microphone, playback, ASR, speaker, acoustic or course-score test. Do not
change production configuration from one saved benchmark example.

Use the installed Pipecat/Silero CPU analyzer, including its real confidence,
400 ms rolling volume, exponential smoothing and run-length state machine.
Feed mono PCM16 at 16 kHz in 20 ms transport chunks, as fast as CPU permits.
Record audio-sample time separately from CPU service time. Fresh analyzer state
per trial avoids dependence on prior trial content. A 750 ms silence prefix is
the warm-silence condition; an immediate clip tests the fresh-volume condition.
Noise-prefix trials use seeded white noise 20 dB below active speech RMS and
retain it throughout the clip.

Development sources are the existing synthetic D2 voice sample and eight new
independently generated utterances. No held-out benchmark clips, labels,
expected answers, judges or transcripts are used by the detector. Apply fixed
0, -6, -12, -18 and -24 dB gains. Find a source waveform reference from the
first and last 10 ms bin above -50 dBFS RMS before applying any gain. These are
repeatable digital energy references, not human acoustic speech labels.

Freeze this diagnostic grid before measurement (stop_secs remains 0.2):

| Name | Confidence | Start seconds | Minimum volume |
| --- | --- | --- | --- |
| baseline | 0.7 | 0.200 | 0.6 |
| start_128 | 0.7 | 0.128 | 0.6 |
| start_096 | 0.7 | 0.096 | 0.6 |
| start_064 | 0.7 | 0.064 | 0.6 |
| confidence_060 | 0.6 | 0.096 | 0.6 |
| volume_050 | 0.7 | 0.096 | 0.5 |
| confidence_060_volume_050 | 0.6 | 0.096 | 0.5 |
| no_volume_diagnostic | 0.7 | 0.096 | 0.0 |

The last row isolates the volume gate; it is not a proposed production default.
The grid separates duration, confidence and volume effects without selecting
from benchmark outcomes. At 16 kHz Silero has 32 ms windows; actual rounded
start-frame budgets must be reported, not just decimal input parameters.

Use 6 s each of synthetic silence, seeded white noise at -45/-30/-15 dBFS RMS,
pink noise at -35/-20 dBFS RMS, isolated click, click train, 40 ms white-noise
bursts, 440 Hz tone and 60 Hz harmonic hum. Count any detected start in these
negative streams; report exposure and event count. These artificial negatives
cannot estimate false interruption rates for TV, speech, laughter or echo.

Report misses, pre-speech starts, waveform-relative onset p50/p95/max, raw
confidence and smoothed-volume gate crossings, CPU service time and detector
source/model hashes. Compare conditions and gain strata before pooling them.
No setting passes a physical playback-stop or backchannel-resume gate here.

Any project change must remain a reversible provisional pause: retain bounded
unplayed PCM, keep capture live, retain SmartTurn/ASR revision and owner/addressee
commit gates, and never authorize foreground/job cancellation or actions from
VAD onset. Test backchannel resumption, empty/noisy ASR, stale results and bounded
queues at the full project boundary before changing the default.
