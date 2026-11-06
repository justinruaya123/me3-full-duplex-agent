# ME3: Pi-default full-duplex agent

Continues `prototype/hermes-duplex-v1` at `642cc73` through
`feat/pi-full-duplex-v1`; the published testing branch is
`hermes/benchmark-latency-v1`. The [November 4 specification](docs/ME3_SPEC_2026-11-04.md)
supersedes the older Hermes-first default. The controller remains harness-neutral;
Hermes and the older OnIt/ME2-related baseline remain available.

A long-lived local runtime owns durable jobs. Voice sessions own microphone,
turns and playback. Ending/muting a voice session leaves delegated work running.
Only committed, owner-verified speech can authorize jobs or previews. Pi workers
never speak and have arbitrary shell/tools disabled; the host validates static
website files, runs trusted syntax checks, and starts read-only loopback previews
only on request. Foreground inference uses a separately configured Qwen or
Nemotron endpoint, with reasoning disabled and exact response model checks.

## Set up and configure

Python 3.13 and Node are required for the Mac setup. Pi `0.84.2` is already
installed in the validation environment. Setup uses isolated environments:

```sh
./scripts/setup-macos.sh --speech-server
# Edit .env: foreground API/model, speech token, wake and verifier configuration.
./scripts/me3.sh doctor
```

The ignored `.env` is created with placeholders without overwriting an existing
file. Fill private operator credentials locally. The tested selection is
`openai-codex/gpt-6.1-sol`; its local RPC and real inference were verified.
Each account/target must verify its own access; no model fallback is automatic.
Configure Pi in the isolated directory selected by `PI_CODING_AGENT_DIR`:

```sh
./scripts/me3.sh pi
# In Pi: /login, then select ChatGPT (OpenAI Codex).
# Or explicitly configure the provider/API key you intend to use.
./scripts/me3.sh pi --list-models sol
./scripts/me3.sh doctor --pi-rpc       # Local protocol/model check, no inference.
./scripts/me3.sh doctor --inference    # Explicit real-provider calls after setup.
```

ChatGPT subscription sign-in and API-key billing are distinct provider choices.
ME3 does not change provider accounts, billing or model selection. See the
[setup guide](docs/SETUP.md) for exact fields, the speaker-verifier contract and
precise remaining acceptance gates.

## Launch

```sh
# Terminal 1: separate authenticated MLX Whisper/Kokoro service.
./scripts/me3.sh speech --check --output .local/voice-check.wav
./scripts/me3.sh speech
# Terminal 2: local runtime and trusted text console.
./scripts/me3.sh console
# Or attach actual Pipecat local audio, after ownership service configuration:
./scripts/me3.sh voice
```

Console commands include `/site build a portfolio`, `/jobs`, `/status ID`,
`/revise ID make it blue`, `/result ID`, `/preview ID`, `/cancel ID`, `/focus ID`,
`go back`, `/end`, and `/start OWNER`. `/end` ends the session; `/quit` explicitly
shuts down the runtime and marks unfinished work interrupted. A restart does
not replay unknown actions. Voice wake opens a candidate; `/enroll OWNER` must
be armed locally before a clean reference can establish ownership. `/mute`
clears capture/reference state independently of inference. Use `/end` and
`/voice` to open a fresh voice session after muting.

## Verify

```sh
.venv313/bin/python -m unittest discover -s tests -v
.venv313/bin/python -m me3.duplex_demo
.venv313/bin/python -m compileall -q me3 tests integrations
./scripts/me3.sh doctor --audio
```

Some tests open loopback sockets. A restricted runner must grant that capability;
a blocked bind is a failed environmental check, never a passed preview test.
Pipeline tests explicitly skip when optional Pipecat is absent. Their inference
and transport fixtures are labelled; they are not acoustic or provider tests.

The unchanged canonical ME3 benchmark is supported through
`integrations/fdbench_entry.py`, with private fresh-session control through the
official assistant/reset hooks. Course runs globally bypass ownership; separate
ownership runs keep it enabled. The final real Mac run completed 60/60 items and
72 recordings using Whisper Turbo, Qwen and Kokoro. E2E mean/p95 was
**2.552/3.711s**, over 29 timed replies; WER was **1.449%**. One of 30 phrase
trials had no recorded reply. ASR final **1.470/2.036s** and TTS p95 **0.696s**
still exceed their targets; small interruption samples and semantic failures
remain unqualified. See [canonical metrics and limits](docs/BENCHMARK.md).

The verified feature branch is `hermes/benchmark-latency-v1`. Follow the
[planned Raspberry Pi pull/setup/testing procedure](docs/RASPBERRY_PI_TESTING.md)
for a later target run. It keeps jobs/orchestration on the Pi and only inference
offloaded. That procedure has not been executed on Raspberry Pi hardware here.

Current evidence, counts, measured software/device probes and unpassed gates
are in [DUPLEX_STATUS](docs/DUPLEX_STATUS.md). No GPT Live parity, p95 acoustic
latency, physical speakerphone/AEC, 30-minute soak or Raspberry Pi qualification is claimed.
