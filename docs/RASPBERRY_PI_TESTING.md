# Planned Raspberry Pi testing

**This procedure has not been executed or validated on a Raspberry Pi here.**
The existing measurements are Mac measurements. Python package resolution,
ARM64 wheels/builds, Pi audio devices, model access, latency and sustained
operation all need evidence from the actual Pi. A successful pull or install
does not pass those gates.

Use this with [SETUP](SETUP.md), [current status](DUPLEX_STATUS.md), the
[November 4 specification](ME3_SPEC_2026-11-04.md) and
[canonical ME3 benchmark instructions](BENCHMARK.md). The runtime and Pi.dev
worker run locally on the Pi. Only model inference may be offloaded: the Mac
may serve Whisper/Kokoro inference, and the configured foreground/worker
providers may serve their selected models. Jobs, orchestration, artifacts,
MCP and action execution remain on the Pi; workers never own speech output.

## Pull main without discarding work

The repository is
`https://github.com/justinruaya123/me3-full-duplex-agent.git`; use branch
`main`. It includes the implementation and evidence from
`hermes/benchmark-latency-v1`. The final measured runtime build was
`6bbbfd57d5e5c062ec3846762158118a7318b0db`; later commits retain its runtime code.
Pull main, including its documentation/results commits, and record the exact
revision you actually test.

For a new checkout:

```sh
git clone --branch main --single-branch \
  https://github.com/justinruaya123/me3-full-duplex-agent.git me3
cd me3
```

For an existing checkout, first inspect `git status --short` and `git remote -v`.
Preserve local work in your own commit, stash or separate checkout before
switching if necessary. The following assumes a clean checkout and the project
repository as `origin`; it does not reset files or rewrite history:

```sh
git fetch origin
if git show-ref --verify --quiet refs/heads/main; then
  git switch main
else
  git switch --track -c main origin/main
fi
git pull --ff-only origin main
git rev-parse HEAD
git status --short
```

If the pull cannot fast-forward, inspect the divergence and preserve the local
commits. Do not replace that failure with `reset --hard`.

## Prepare a Pi environment

Use 64-bit Linux on the target Pi. [pyproject.toml](../pyproject.toml) declares
Python **>=3.11**; the installed Pi CLI package declares Node **>=22.19.0**.
Check the actual system before installing:

```sh
uname -m
getconf LONG_BIT
cat /etc/os-release
python3 --version
node --version
npm --version
```

The intended architecture is `aarch64` with a 64-bit OS. Install a compatible
ARM64 Node runtime if the distribution's Node package is older than 22.19.0.
The Mac's tested Node 24.13.0 is a host receipt, not a Pi installation result.

On Debian-based Raspberry Pi OS, the following is a candidate prerequisite
list; OS package names and sufficient build dependencies remain unverified on
the target OS:

```sh
sudo apt update
sudo apt install git python3-venv python3-dev build-essential pkg-config \
  libportaudio2 portaudio19-dev libasound2-dev libsndfile1
```

Create a separate portable runtime environment from the project root:

```sh
python3 -m venv .venv-pi
.venv-pi/bin/python -m pip install --upgrade pip
.venv-pi/bin/python -m pip install -e '.[test,mcp]'
```

The core has no mandatory runtime dependencies. The selected extras add the
test/MCP/HTTP dependencies declared by the project. Record an installation
failure rather than silently changing versions or selecting a mock provider.

The Mac bootstrap and wrappers contain `.venv313` and `.speech-venv312` paths.
Do not use `scripts/setup-macos.sh` as a Pi installer or assume those wrappers
select `.venv-pi`. Use explicit `.venv-pi/bin/python` commands below. Likewise,
`requirements-macos.lock.txt` and `requirements-speech-macos.lock.txt` are Mac
receipts, not ARM64-Linux locks. Do not install MLX or the `speech-server` extra
on the Pi.

## Install optional real voice/transport dependencies

The existing [requirements-duplex.txt](../requirements-duplex.txt) selects:

- `pipecat-ai[openai,local]` at Git commit
  `6f777a0ef3bb98163d10d708525a0db21cda5fbf`.
- `pywebrtc-audio==0.2.0` for the playback-reference AEC adapter.

Installed Mac metadata identifies that Pipecat source as `1.15.1.dev12`, requiring
Python >=3.11. It provides the `openai` and `local` extras used by this recipe;
`local` requires PyAudio. The selected SmartTurn V3 implementation uses its
bundled ONNX model and NumPy feature extraction. Its separate
`local-smart-turn` extra pulls additional CoreML/transformer/torch dependencies
and is not required for that inspected ONNX path.

These observations establish the intended dependency recipe, not Pi wheel or
build compatibility. In particular, ONNX Runtime, NumPy/soxr, PyAudio and
`pywebrtc-audio` must resolve/build on the actual Linux/Python/ARM64 combination.

```sh
.venv-pi/bin/python -m pip install --dry-run -r requirements-duplex.txt
# After reviewing a supported ARM64 resolution/build path:
.venv-pi/bin/python -m pip install -r requirements-duplex.txt
```

If this cannot install, record the voice stack as blocked. Do not remove turn,
ownership or cancellation gates to make an import check pass. Headphone and
speakerphone/AEC qualification remain separate even after installation.

## Give the local Pi worker its own sign-in

The actual installed package was **`@earendil-works/pi-coding-agent@0.84.2`**,
with the `pi` executable and Node engine >=22.19.0. This matches
[the Mac setup recipe](../scripts/setup-macos.sh). Install it locally on the Pi:

```sh
npm install --prefix .local/pi-cli @earendil-works/pi-coding-agent@0.84.2
mkdir -p .local/pi
chmod 700 .local/pi
export ME3_PI_BIN="$PWD/.local/pi-cli/node_modules/.bin/pi"
export PI_CODING_AGENT_DIR="$PWD/.local/pi"
"$ME3_PI_BIN" --version
"$ME3_PI_BIN"
```

Use Pi's interactive `/login` with your own account/provider on the Pi, then
inspect `"$ME3_PI_BIN" --list-models sol`. Do not copy Mac auth state into Git
or assume a catalog entry proves entitlement. Mac RPC and actual Sol inference
were verified separately; the Pi must verify its own access. ChatGPT sign-in
and an explicitly selected API-key provider are different choices.

The current Mac comparison selected worker provider `openai-codex` and exact
model `gpt-6.1-sol`. Set those explicitly only with the intended account/model
access; do not silently select another model if it is unavailable. The host
adapter launches local Pi RPC with tools/extensions/skills/context discovery
disabled, preserving the host-owned job and artifact boundary.

## Configure inference endpoints privately

Create the local settings file without overwriting one you already maintain:

```sh
if [ ! -e .env ]; then
  cp .env.example .env
fi
chmod 600 .env
```

Edit it locally. Keep secrets in this ignored file/operator environment and
Pi's private auth directory, never in code, commits, benchmark fixtures or chat.
Use [SETUP's settings table](SETUP.md#operator-settings) for the complete names.
The Pi needs its own local `ME3_PI_BIN`, `PI_CODING_AGENT_DIR` and state paths.

For a comparable run, preserve the Mac's exact selections:

| Role | Selection / Pi setting |
| --- | --- |
| Foreground | `ME3_FOREGROUND_PROFILE=qwen`, exact `Qwen/Qwen3.8-27B`, operator endpoint/key; thinking remains disabled by the existing backend |
| Worker | `ME3_HARNESS=pi`, `ME3_WORKER_PROVIDER=openai-codex`, `ME3_WORKER_MODEL=gpt-6.1-sol`; local Pi CLI and own sign-in |
| Recognition | `ME3_ASR_MODEL=mlx-community/whisper-large-v3-turbo`; authenticated Mac LAN `/v1` base URL |
| Speech | `ME3_TTS_MODEL=mlx-community/Kokoro-82M-bf16`, `ME3_TTS_VOICE=af_heart`; authenticated Mac LAN `/v1` base URL |
| Ownership | A deliberate wake phrase plus an actual independent authenticated speaker/overlap/addressee verifier for normal voice mode |

The speech URLs in `.env.example` use loopback. On a Pi, `127.0.0.1` means the
Pi, so replace those ASR/TTS bases with the Mac's actual private LAN address,
for example the form `http://MAC_LAN_ADDRESS:8002/v1`. Keep real addresses and
tokens local. Set the Pi's ASR/TTS keys to the Mac service's operator-selected
token. The speech service is inference-only; it does not run the Pi's controller
or autonomous worker.

On the **Mac only**, use its existing speech environment and private settings.
After setting the shell variable `ME3_MAC_LAN_ADDRESS` to its actual LAN bind
address, the existing Mac command is:

```sh
./scripts/me3.sh speech --host "$ME3_MAC_LAN_ADDRESS" --port 8002
```

Wait for successful model warm-up and the listening banner. Keep the service
authenticated and scoped to the intended private network. Do not expose a
public deployment or put credentials in URLs. LAN availability and latency from
the Pi are still unverified.

## Run installed checks on the Pi

From the project root, load the local operator environment without printing it:

```sh
set -a
. ./.env
set +a
.venv-pi/bin/python -m me3.doctor
.venv-pi/bin/python -m me3.doctor --pi-rpc
.venv-pi/bin/python -m unittest discover -s tests -p '*v1.py' -v
.venv-pi/bin/python -m unittest discover -s tests -v
.venv-pi/bin/python -m me3.duplex_demo
.venv-pi/bin/python -m compileall -q me3 tests integrations
```

Record exact pass/failure/skip counts and command exit codes. Socket tests need
local socket capability; a denied bind is an environmental failure. Missing
optional Pipecat tests may skip and must be reported. The demo is a control
simulation, not an acoustic/device result. The RPC check makes no model request.

Normal-voice configuration can remain blocked until the real ownership verifier
is supplied, even when an individual RPC/provider subprobe succeeds. Do not
report the whole doctor check as ready from one passing subprobe. Explicit
subsequent probes are:

```sh
# Actual foreground + worker provider requests, after own sign-in/configuration:
.venv-pi/bin/python -m me3.doctor --inference
# Device enumeration + synthetic ONNX turn smoke, without microphone capture:
.venv-pi/bin/python -m me3.doctor --audio
# Trusted local text console; actual voice additionally requires ownership setup:
.venv-pi/bin/python -m me3.runtime
# Opens real local audio after the required ownership configuration is supplied:
.venv-pi/bin/python -m me3.runtime --voice
```

Ending/muting voice does not cancel jobs. Keep speech interruption, foreground
cancellation and explicit job cancellation distinct during manual checks.

## Use only the canonical ME3 benchmark

Use the unchanged external repository at commit
**`57eaddbc188ce9a19b8fd002b575f703426956f4`**, with its official complete dataset,
runner and scorer. Do not use custom subsets, development clips, a simulator,
custom phrases or revised scoring rules as acceptance evidence.

For a fresh benchmark checkout, from the project root:

```sh
git clone https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking.git \
  .local/fd-benchmark-20261107
git -C .local/fd-benchmark-20261107 checkout --detach \
  57eaddbc188ce9a19b8fd002b575f703426956f4
python3 -m venv .local/fd-benchmark-20261107/.venv
.local/fd-benchmark-20261107/.venv/bin/python -m pip install \
  -r .local/fd-benchmark-20261107/requirements.txt psutil==7.2.2
.venv-pi/bin/python -m pip install psutil==7.2.2
.local/fd-benchmark-20261107/.venv/bin/python \
  .local/fd-benchmark-20261107/tools/fetch_datasets.py
```

Do not overwrite an existing checkout or dataset blindly. The pinned official
fetcher selects release `datasets-v2`, asset `fdbench-datasets-v2.zip`, and checks
the archive's SHA-256 before extracting. Retain its complete manifest and license
files. Inspect preflight for missing files/groups; they are not passed strata.
The benchmark requirements are also subject to unverified ARM64 wheel/build
availability.

Prefer the runner **and agent on the Pi**, with loopback direct transport and
`--where local`. The Mac serves only the configured model inference. This keeps
the measured scheduling/transport/client workload on the Pi. Use the same
[entry/runtime](../integrations/fdbench_entry.py) and declare the global `course`
ownership bypass; it is not an ownership success. Never pass scenario labels,
expected behavior or judge output into the runtime.

The following Bash setup uses the existing
[fresh-session wrapper](../integrations/benchmark_control.py), not a new runner.
Its instance/control directory must be new; do not pre-create the control
directory. Paths are quoted with Python's `shlex.join` for the two official
command hooks:

```sh
# Project root; .env was loaded above. No secrets are passed in command arguments.
me3_project="$PWD"
me3_pi_python="$me3_project/.venv-pi/bin/python"
me3_bench="$me3_project/.local/fd-benchmark-20261107"
me3_instance="me3-pi-$(date -u +%Y%m%dT%H%M%S)-$$"
me3_control="/tmp/$me3_instance"
me3_logs="$me3_project/.local/qualification/$me3_instance"
mkdir -p "$me3_project/.local/qualification"
export FDBENCH_PROJECT="$me3_project"
export FDBENCH_ENTRY="$me3_project/integrations/fdbench_entry.py"
export FDBENCH_ASSISTANT_PYTHON="$me3_pi_python"
export ME3_BENCHMARK_PROFILE=course

me3_assistant_cmd=$(
  "$me3_pi_python" -c 'import shlex,sys; print(shlex.join(sys.argv[1:]))' \
    "$me3_pi_python" "$me3_project/integrations/benchmark_control.py" serve \
    --control-dir "$me3_control" --instance "$me3_instance" \
    --project "$me3_project" --launcher "$me3_bench/launch_assistant.py" \
    --python "$me3_pi_python" --log-root "$me3_logs"
)
me3_reset_cmd=$(
  "$me3_pi_python" -c 'import shlex,sys; print(shlex.join(sys.argv[1:]))' \
    "$me3_pi_python" "$me3_project/integrations/benchmark_control.py" reset \
    --control-dir "$me3_control" --instance "$me3_instance"
)
"$me3_pi_python" "$me3_bench/launch_assistant.py" --check \
  --project "$me3_project"
cd "$me3_bench"
.venv/bin/python -m fdbench check --connect direct --where local \
  --project "$me3_project" --judge-provider none
.venv/bin/python -m fdbench run --student me3-pi --rounds 1 \
  --phrases 10 --runs 3 --seed 231 --gap 6 --connect direct --where local \
  --project "$me3_project" --judge-provider none --no-score --yes \
  --recordings r --no-live --assistant-cmd "$me3_assistant_cmd" \
  --reset-cmd "$me3_reset_cmd"
```

This is the canonical ten-phrase x three-run block plus a **complete** duplex
round. With the complete official dataset it schedules 40 queue items and 44
recording variants, including the four v1.5 clean twins. Record actual counts,
errors, missing replies, overlaps not played, and clean twins; do not replace
those denominators with only successful stop measurements. Increase complete
rounds only as a declared protocol choice, keeping the phrase block, seed,
models and scorer comparable. One round does not establish reliable per-stratum
rates or an acoustic p95.

The wrapper starts a fresh local child/runtime/log tree between independent
recordings, including clean twins, through the upstream `--reset-cmd` hook.
Six seconds of silence alone is not a session reset. A wrapper startup/reset
failure is a failed run condition, not permission to continue an older session.
Keep its session logs alongside the official raw run.

## Score raw runs and record where evaluation happened

Scoring dependencies may be easier on the Mac. The unchanged scoring recipe is
`requirements-score.txt`, `--judge-provider none --no-utmos --asr-model small`.
Its evaluation recognizer is `Systran/faster-whisper-small`, CPU int8, separate
from the agent's Mac-hosted MLX Whisper large-v3-turbo. Do not silently choose
`tiny`/`base` to make a Pi score easier and then compare it as the same evaluator.
No judge or UTMOS means no qualified content-relevance/Respond/Resume or MOS claim.
Preserve the comparison run's effective evaluator versions when possible; a
different resolved package stack must be disclosed rather than assumed identical.

If the Pi supports those scoring dependencies, install them in the benchmark
venv and score the actual run directory printed by the runner:

```sh
# In the pinned benchmark checkout; replace RUN_ID with the actual printed ID.
.venv/bin/python -m pip install -r requirements-score.txt
.venv/bin/python -m fdbench score runs/me3-pi/RUN_ID \
  --judge-provider none --no-utmos --asr-model small
```

Alternatively, copy the **entire raw run** to the Mac, including queue/session
JSON, per-trial timing/stage/stat files, `her.flac`, `played.flac` and clean twins.
Preserve the Pi original; score a copy using the same pinned benchmark checkout
and the same evaluator settings. For example, from the Mac:

```sh
# Replace the SSH account/host and absolute Pi run path with the real local values.
mkdir -p /absolute/private/pi-run-evidence
scp -r pi-user@PI_HOST:/absolute/benchmark/runs/me3-pi/RUN_ID \
  /absolute/private/pi-run-evidence/
# In the Mac's existing benchmark checkout pinned to 57eaddbc...:
cd /absolute/Mac/benchmark-checkout
.venv/bin/python -m fdbench score /absolute/private/pi-run-evidence/RUN_ID \
  --judge-provider none --no-utmos --asr-model small
```

The first score may need the public evaluation-model download; offline mode is
valid only after that cache is present. Record the evaluator machine, Python,
packages, model and settings separately. Pi-captured runtime timings remain Pi
runtime evidence; Mac evaluation compute time is not Pi ASR latency. Conversely,
Mac runtime recordings cannot become Pi measurements by copying/scoring them
on the Pi. Do not silently adjust the recorded clocks or subtract LAN overhead.

## Evidence required before claiming Pi qualification

Retain exact agent and benchmark commits, clean/dirty source state, official
dataset release/checksum receipt, OS/architecture/Python/Node/Pi CLI/package
versions, exact model IDs, private endpoint topology, audio rates, profile,
seed, complete rounds, reset session logs and evaluator provenance. Keep tokens
out of receipts and review artifacts before sharing. Runtime/evaluation package
freezes are target receipts, not claims of portable dependency locks.

After core tests and real canonical benchmark scoring, the remaining gates
include actual Pi headphone capture/playback; owner/addressee/mixed/replayed
speech; false/missed interruptions and backchannel resumption; stale-result and
failure/mute behavior; durable work while conversing and returning its result;
idle/busy-worker and Mac-inference contention; LAN failure; physical
speakerphone AEC/double-talk; accents and long turns; and a 30-minute Pi CPU,
memory, temperature and audio-dropout soak. Record unavailable sensors explicitly.

Use [DUPLEX_STATUS](DUPLEX_STATUS.md) for measured results and unpassed gates.
Neither this planned procedure nor Mac software/device evidence establishes
Raspberry Pi acceptance, GPT Live parity, or the specification's acoustic
250 ms interruption / 1 s substantive-response targets.
