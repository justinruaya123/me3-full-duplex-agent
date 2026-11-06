# Reproducible setup and qualification

## Environment

Validated development setup: macOS arm64, Python 3.13.6, Node 24.13.0,
Pi coding agent 0.84.2, Pipecat source
`6f777a0ef3bb98163d10d708525a0db21cda5fbf`. The runtime environment is
`.venv313`; the separate MLX service uses Python 3.12.13 in `.speech-venv312`.
Kokoro/Misaki require Python <3.13; setup installs a project-local Python 3.12
with uv when a system Python 3.12 is unavailable.
Install from the repository using `./scripts/setup-macos.sh --speech-server`.
PortAudio is an OS prerequisite for Pipecat local audio; on a Mac without it,
install it using your system package manager before setup. No global Python
packages, provider logins or billing settings are changed by setup.

`requirements-macos.lock.txt` and `requirements-speech-macos.lock.txt` record
installed distributions for this host. They are Mac receipts for runtime Python 3.13 and speech Python 3.12, not
an ARM64-Linux lock. For a matching fresh host, create the corresponding venv,
install its lock with `python -m pip install -r LOCK`, then `pip install -e .`.

## Operator settings

Edit the ignored `.env`, then use `scripts/me3.sh` to load it. No key values are
printed by `doctor`. A missing provider produces an explicit error, never mock
inference. The default `doctor` reports configuration only; `--pi-rpc` checks
local Pi protocol/model selection; `--inference` explicitly invokes models.

| Role | Settings | Expected selection |
| --- | --- | --- |
| Worker | `ME3_HARNESS`, `ME3_PI_BIN`, `ME3_WORKER_PROVIDER`, `ME3_WORKER_MODEL` | Pi; explicit exact Sol ID. November 6 selection: `openai-codex`, `gpt-6.1-sol` (real inference verified after sign-in) |
| Worker auth | `PI_CODING_AGENT_DIR` and Pi `/login`; optional `ME3_WORKER_API_KEY_ENV` | ChatGPT sign-in or an explicitly chosen API provider; no implicit switch |
| Foreground | `ME3_FOREGROUND_PROFILE`, `ME3_FOREGROUND_BASE_URL`, `ME3_FOREGROUND_MODEL`, `ME3_FOREGROUND_API_KEY` | One Qwen or Nemotron profile; exact served ID from that endpoint |
| ASR | `ME3_ASR_BASE_URL`, `ME3_ASR_MODEL`, `ME3_ASR_API_KEY` | `mlx-community/whisper-large-v3-turbo` through the separate MLX service |
| TTS | `ME3_TTS_BASE_URL`, `ME3_TTS_MODEL`, `ME3_TTS_VOICE`, `ME3_TTS_API_KEY` | `mlx-community/Kokoro-82M-bf16`, `af_heart` |
| Speech service | `ME3_SPEECH_SERVER_TOKEN` | Choose your own token; set ASR/TTS keys to match when using the included service |
| Voice identity | `ME3_WAKE_PHRASE`, `ME3_SPEAKER_BASE_URL`, `ME3_SPEAKER_API_KEY` | Explicit phrase and independent authenticated verification service |
| Persistence | `ME3_STATE_DIR` | Stable local directory; single supervisor lock |

The installed Pi provider documentation supports `/login` for ChatGPT Plus/Pro
under OpenAI Codex, and API-key providers via their own configuration. Run
`./scripts/me3.sh pi`, authenticate yourself, and inspect
`./scripts/me3.sh pi --list-models sol`. The isolated directory is `.local/pi`.
A packaged model catalog entry does not prove account entitlement. Only a
successful `doctor --inference` and a real website job qualify provider access.
An API key for one provider cannot stand in for another provider's subscription.

On November 6 the operator configured `Qwen/Qwen3.8-27B`. Two real provider
checks and a two-turn test through the actual controller passed; receipts are in
`docs/evidence/2026-11-06/d1/`. The endpoint and key remain operator settings in
the ignored `.env`. ME3 sends `chat_template_kwargs.enable_thinking=false` and
rejects reasoning content or a different/missing response model ID. The live
checks observed no reasoning or tool-call deltas; this does not establish audio
latency or benchmark qualification. The controller exposes no LLM-selected tool
execution and adds no third model. After separate Pi sign-in in its isolated
directory, real Sol inference also passed, together with foreground conversation
while a real job ran and retrieval after ending/reopening its session. See
`docs/evidence/2026-11-06/d1/authenticated/`. Foreground and Pi authentication
remain separate. These checks complete D1's model-access/runtime gate; they do
not qualify speech inference or the real website workflow.

## Separate speech service

The November 7 checkout has the exact ASR/TTS IDs and matching private local
speech keys configured in ignored `.env`. On a fresh installation choose one
local token and set `ME3_SPEECH_SERVER_TOKEN`, `ME3_ASR_API_KEY` and
`ME3_TTS_API_KEY` to that same value. These authenticate the local service;
they are separate from foreground Qwen and Pi provider authentication.

First run the bounded real-model check:

```sh
./scripts/me3.sh speech --check --output .local/voice-check.wav
```

It generates “Hello. The voice system is ready.” with the exact Kokoro model
and voice, resamples the generated audio for Whisper, and requires the known
transcript before reporting success. The optional output is synthetic mono
PCM16 WAV at 24kHz. No microphone is opened. The check has a 90-second deadline,
kills/reaps its process group on failure and caps its report at 64KiB.

Then start the persistent service:

```sh
./scripts/me3.sh speech --host 127.0.0.1 --port 8002
```

The service warms and checks both models before listening. Its parent process
enforces a startup deadline and terminates the native model process on stop;
Ctrl+C or SIGTERM also cleans up an in-flight native inference. Wait for the
listening banner before connecting a voice client. A successful model catalog
alone is not a scored speech/ownership/acoustic qualification.

The service exposes authenticated `GET /v1/models`,
`POST /v1/audio/transcriptions` (multipart WAV PCM16/16kHz mono, <=16s), and
`POST /v1/audio/speech` (raw PCM16/24kHz mono). ASR supplies word timestamps;
the controller's rolling snapshots attach session/turn/revision timing. MLX
imports occur only in this process; the Pi runtime makes authenticated HTTP
inference calls. LAN endpoints require keys. Deliberately select a LAN bind
address if using a Pi; never expose this service as a public deployment.

The November 7 optimized build reuses byte-identical Whisper encoder features
within one native request, with request cleanup on success/failure. It preserves
full context, automatic language detection, word timestamps and the selected
weights. Capture can reuse an identical current-generation recognition while
still requiring final turn approval. No new API settings or dependencies are
needed. The real rerun reduced E2E mean 5.422s -> 3.639s and ASR final mean
4.454s -> 2.786s; p95 and duplex qualification remain open. See
[the measured comparison](evidence/2026-11-07/latency-improvement/README.md).

Kokoro requires `misaki[en]`; this dependency is included. The first model use
can download weights. Existing small Whisper weights do not satisfy the
large-v3-turbo selection and are never used as fallback.

Primary API references:
[MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper),
[Kokoro MLX](https://github.com/Neywa-Labs/mlx-audio/blob/main/docs/models/tts/kokoro.md).

## Ownership verifier contract and remaining implementation boundary

Live ownership mode requires an independent service, not an inference from
Silero/SmartTurn. No speaker/overlap/addressee engine is bundled or claimed
qualified by the HTTP adapter. Configure an actual service before voice use:

- `POST BASE/enroll`: `pcm16_16000` (base64, >=2s); returns `clean: true` and
  `mixed: false` only for an appropriate reference.
- `POST BASE/verify`: `reference_pcm16_16000`, `query_pcm16_16000`, `text`;
  returns `match`, `mixed`, `addressed` booleans from independent analysis.
- Both require `Authorization: Bearer TOKEN`. Unknown/missing overlap or
  addressee evidence fails closed. The service must not retain reference/query
  audio. ME3 keeps only the session reference in memory and erases it on close.

Wake opens a candidate. The operator must deliberately arm `/enroll OWNER` in
the console; the next complete clean enrollment sample may establish ownership.
Other wakes cannot steal the session. Owner labels are trusted local-operator
bindings, not strong authentication for sensitive actions. Unseen/replayed/mixed
speaker qualification remains required. `--voice` fails explicitly when this
service/wake configuration is absent. Do not turn a course ownership bypass into
an end-to-end ownership claim.

Current audio defaults to a headphone baseline. Set `ME3_AUDIO_MODE=speakerphone`
to enable WebRTC AEC3 before VAD, using rate-converted actual transport playback
as the reference. `ME3_AEC_DELAY_MS` is an explicit device-delay hint. The DSP
adapter is software-smoke-tested; physical echo/double-talk is unqualified.
Licensed Krisp interruption prediction is not implemented/qualified. Provisional VAD
pauses preserve unplayed PCM; accepted backchannels resume it; confirmed turns
invalidate obsolete output. ASR uses bounded rolling whole-turn windows, stable
prefix reconciliation and SmartTurn readiness. Inputs longer than 16 seconds
are explicitly discarded rather than executing a fragment. Cached autonomous
Kokoro backchannels and long-dictation stitching remain unpassed requirements.
Transport receipts are whole-clause software write receipts, not acoustic proof
or word-aligned heard-prefix tracking. There is no claim that all specification
acceptance criteria are finished.

## Website demonstration

```text
/site build a responsive portfolio with an about section
/jobs
/status JOB_ID
/result JOB_ID
/revise JOB_ID change the accent color to blue
/preview JOB_ID
/focus JOB_ID
Tell me about that design
 go back
/end
/start local-operator
```

Pi persists a session per job and awaits `agent_settled`, after a new assistant
message, before requesting final text. Worker tools/extensions/skills/templates
and context-file discovery are disabled. The host accepts <=32 static files,
<=1MiB JSON, safe relative paths, HTML/CSS/JS/SVG/text; no package.json or arbitrary
build scripts. A trusted Node syntax check, viewport check and file hash receipt
must pass before completion. This verifies a static build, not browser behavior.
Preview is explicit, loopback-only, read-only, CSP-restricted and current-revision
checked. Revisions close old previews. Cancellation preserves already-saved files
and reports that fact. Public deployment is not authorized by a preview request.

## Reproduce checks

```sh
.venv313/bin/python -m unittest discover -s tests -v
.venv313/bin/python -m me3.duplex_demo
.venv313/bin/python -m compileall -q me3 tests integrations
./scripts/me3.sh doctor --pi-rpc --audio
# After credentials/endpoints are configured:
./scripts/me3.sh doctor --inference
```

## Course benchmark

The latest tested copy is `.local/fd-benchmark-20261107` at
`57eaddbc188ce9a19b8fd002b575f703426956f4`. The older
`.local/fd-benchmark` at `106ac8e543a5fd996e254a87e69fa101bfd27a42` is preserved.
The scorer is unchanged. Both November 7 real-model runs completed 40 queue
items / 44 recordings each, scored with real evaluation ASR and Praat.
See [results and limits](BENCHMARK.md) and
[the evidence](evidence/2026-11-07/course-benchmark/README.md).

For a **fresh benchmark copy only**, from the project root (the current copy
is already installed and has its verified dataset):

```sh
git clone https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking.git \
  .local/fd-benchmark-20261107
git -C .local/fd-benchmark-20261107 checkout --detach \
  57eaddbc188ce9a19b8fd002b575f703426956f4
.speech-venv312/bin/python -m venv .local/fd-benchmark-20261107/.venv
.local/fd-benchmark-20261107/.venv/bin/python -m pip install \
  -r .local/fd-benchmark-20261107/requirements.txt \
  -r .local/fd-benchmark-20261107/requirements-score.txt psutil==7.2.2
.venv313/bin/python -m pip install psutil==7.2.2
.local/fd-benchmark-20261107/.venv/bin/python \
  .local/fd-benchmark-20261107/tools/fetch_datasets.py
```

The official fetch verifies the release checksum. Its scoring ASR is
`Systran/faster-whisper-small`, CPU int8, separate from the agent's exact MLX
Whisper model. The first score downloads those public evaluation weights;
the measured run used the downloaded cache with `HF_HUB_OFFLINE=1`.
No judge was selected and UTMOS was not installed; those are unscored gates.

Start `./scripts/me3.sh speech` in one terminal and wait for its listening
banner. In another terminal at the project root:

```sh
set -a
. ./.env
set +a
export FDBENCH_PROJECT="$PWD"
export FDBENCH_ENTRY="$PWD/integrations/fdbench_entry.py"
export FDBENCH_ASSISTANT_PYTHON="$PWD/.venv313/bin/python"
export ME3_BENCHMARK_PROFILE=course
.venv313/bin/python .local/fd-benchmark-20261107/launch_assistant.py --check
cd .local/fd-benchmark-20261107
.venv/bin/python -m fdbench run --student me3-local --rounds 1 \
  --phrases 10 --runs 3 --seed 231 --connect direct --where local \
  --judge-provider none --no-score --yes --recordings r --no-live
# Use the run directory printed above for a new measurement.
.venv/bin/python -m fdbench score runs/me3-local/2026-11-07_02-16-38 \
  --judge-provider none --no-utmos --asr-model small
```

Direct feed opens no microphone or speaker. The course profile globally
bypasses ownership; `ownership` enables it. No scenario labels are read by the
agent. Default six-second gaps leave conversation and incomplete capture state
intact; the current run is a continuous-session diagnostic. Independent trials
still require a fresh build/session through the upstream `--reset-cmd` hook;
that integration is not implemented. One round is insufficient for reliable
per-stratum rates/p95, and content labels need an explicitly configured judge.
The launcher `READY` result alone is only an import/rate contract check.

Pi deployment: use 64-bit Linux, Python >=3.11, Node, Pi CLI, PortAudio and the
portable runtime dependencies; configure authenticated M2 speech endpoints.
Do not install MLX on the Pi. Before qualification, repeat device/provider tests,
idle/busy contention and failures, speakerphone echo/double-talk, accents and the
30-minute CPU/memory/temperature/dropout soak on the actual Pi4/4GB. Mac results
and software fixture timing do not satisfy those gates.
