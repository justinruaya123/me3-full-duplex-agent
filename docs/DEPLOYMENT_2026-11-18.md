# Two-host deployment · November 18, 2026

The client captures 16 kHz mono speech, sends it to authenticated Whisper on the speech server, and commits turns locally with Silero, SmartTurn, and owner verification. The same client runs Pipecat, SQLite, the Pi.dev process, Brave requests, website verification, and the speaker. New client setups use CPU Kokoro ONNX. Change `ME3_TTS_BACKEND` to `server` to explicitly use the speech server's MLX Kokoro. Both routes feed the same 24 kHz playback scheduler.

## Speech server

On the Apple Silicon inference host, install only the speech service and its dependencies. Configure the MLX Whisper and Kokoro model IDs, voice, and a nonempty private `ME3_SPEECH_SERVER_TOKEN` in that host's private `.env.speech-server`. Use the private LAN bind address for this machine. The service warms both MLX models before binding. The client needs the matching speech token even for loopback. Keep OpenRouter, Brave, owner profiles and the Pi harness on the client.

```sh
./scripts/setup-macos.sh --speech-server-only
./scripts/me3.sh speech --check
./scripts/me3.sh speech --host "$ME3_MAC_LAN_ADDRESS" --port 8002
```

## Client

Use the Linux ARM64 environment and native audio dependencies from the [Pi setup](RASPBERRY_PI_TESTING.md). On a Mac client use `./scripts/setup-macos.sh`. Set `client_python=.venv-pi/bin/python` on the Pi or `client_python=.venv313/bin/python` on the Mac. Install the local TTS and browser extras and the matching Chromium. On Linux, Playwright may also need distribution packages via `playwright install --with-deps chromium`.

```sh
"$client_python" -m pip install -e '.[test,mcp,local-tts,website]'
"$client_python" -m playwright install chromium
```

The US English client voice uses speaker 0 of the upstream sherpa-onnx Kokoro int8 v1.0 bundle. The worker verifies SHA-256 of the model, voice table, tokens and English lexicon when it starts. Install the exact archive once on the client from the repository root. These commands use a temporary download and extract only after the checksum succeeds.

```sh
(
  set -e
  archive=$(mktemp)
  trap 'rm -f "$archive"' EXIT
  curl --fail --location --output "$archive" \
    https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_0.tar.bz2
  echo "72c347230107ef8a31098ec4d468a605244beef5f1ed00db97efa13518800653  $archive" | shasum -a 256 -c -
  mkdir -p .local/models
  tar -xjf "$archive" -C .local/models
)
```

Start from [.env.example](../.env.example). Set `ME3_ASR_BASE_URL` to the inference host's private `/v1` URL. Configure the ASR token, wake phrase, and the authenticated verifier on client loopback. Choose the foreground and worker independently in the client’s private `.env` using the [role matrix](SETUP.md). Supply an OpenRouter key for a selected OpenRouter role and a Brave key for live lookups. The verifier is an operator-supplied service. Normal voice requires a clean enrollment and explicit match, overlap and addressee evidence. Keep `ME3_MEMORY_ENABLED=0` until the operator chooses to retain owner data. Server TTS additionally requires its URL, model, voice and LAN token. A missing asset or service produces a failure on the selected route.

```sh
./scripts/me3.sh doctor
./scripts/me3.sh tts-probe --roundtrip
ME3_TTS_BACKEND=server ./scripts/me3.sh tts-probe --roundtrip
./scripts/me3.sh doctor --inference
./scripts/me3.sh console
./scripts/me3.sh voice
```

The TTS probe synthesizes the same public test sentence twice. It reports software first PCM, generated duration and RTF. `--roundtrip` sends only its synthetic audio to the selected Whisper route. Client child-process RSS and CPU describe local synthesis. Server resource usage requires sampling the inference host.

## Exercise the handoff

| Operation | Example and observable result |
| --- | --- |
| Current information | Ask “What is the latest weather in Manila?” or `/lookup launches from 2026-11-01 to 2026-11-07`. Answers supplies cited excerpts for a quick answer. An explicit window selects Web Search. The console prints source URLs, retrieval time and available source dates. Missing credentials or an unsupported response produces an explicit lookup failure. |
| Approve a public fact | With memory enabled, enter `/profile public bio = I study acoustics`. Earlier private notes require explicit approval before publication. |
| Delegate and revise | Enter `/site create a website about me`, continue a separate conversation, then `/revise ID make it blue`. The host validates the current revision and checks desktop and mobile rendering offline. A preview opens only on `/preview ID`. |
| Return and report | Say “go back” for current status. Interrupt a result and say “continue” to resume its outstanding report. Check the durable job ID and revision across session end. |

See [provider routing and smoke checks](OPENROUTER.md), [profile commands and privacy](MEMORY.md), and [delivery state and recovery](JOB_REPORTING.md).

## Qualification

Use separate measurements for fixture control, live providers, direct course transport and physical acoustics. Pin the source revision, model hashes, voice, worker state, board, RAM, OS, Hailo connection if present, and audio interface. Repeat cold/warm speech checks idle and with a live worker. Record sustained RTF, CPU/RAM and underruns throughout the 30-minute target soak. Keep the course scorer and thresholds in [BENCHMARK](BENCHMARK.md). Test physical double-talk and count audible replies on a shared input/output recorder. Freeze thresholds before held-out runs and collect at least 100 eligible observations per claimed p95 stratum. Current measurements and open gates are in [DUPLEX_STATUS](DUPLEX_STATUS.md).
