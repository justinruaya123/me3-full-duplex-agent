# ME3: harness-neutral duplex voice prototype

**Current branch: `prototype/hermes-duplex-v1`. Hermes first; Pi RPC alternative.**

This is a control-plane prototype, not a measured replacement for a native
speech-to-speech model. It extends the previous implementation on **`perliminary`**
(commit `6a044dba1edb0d0edba998954def39dbc0158d51`). The misspelled branch contains
the prior code; `main` and `preliminary` did not contain it when work began.

## Architecture

```text
microphone / benchmark transport
        | continuously captured audio
        v
  VAD + ASR  ----> conversational controller <---- transport playback events
                        |             |
             quick conversational    +---- durable local task supervisor
                  response                        |
                        |                 isolated Hermes / Pi workers
                 speech arbiter                   |
                        |                 revision-fenced result artifacts
                    TTS/audio <---- idle-boundary completion notice
```

The controller owns speaking rights. Neither a worker nor its result may directly
speak or switch conversation focus. Stopping speech does not cancel a job.
Hermes/Pi processes, persistence and tool ownership stay on the orchestration
machine; only inference endpoints may be elsewhere. No ME2 smart-speaker code
or constrained-command grammar is changed.

See [the architecture and qualification plan](docs/DUPLEX_ARCHITECTURE.md) and
[the measured implementation status](docs/DUPLEX_STATUS.md).

## Run the dependency-free simulation

Python 3.11+ on Linux/macOS:

```sh
python -m me3.duplex_demo
python -m unittest discover -s tests -p '*v1.py' -v
python -m compileall -q me3 tests integrations
```

The demo uses **in-memory fixture jobs and fixture text**, not real inference,
durable-job validation or audio. The original `python -m me3 demo` and the OnIt
modules remain available as a separate legacy baseline.

## Real providers: explicit configuration, no fallback

Install the project and the inspected Pipecat source in the voice environment.
Local audio needs the operating system's PortAudio development/runtime packages.

```sh
python -m pip install -e '.[test]'
python -m pip install -r requirements-duplex.txt
```

Install Hermes from source in its own environment, following its installation
instructions (`uv sync` from the checkout), then check out the adapter revision
**before** syncing. Do not substitute an unrelated package named `hermes-agent`.

```sh
git clone https://github.com/NousResearch/hermes-agent.git "$HOME/hermes-agent"
git -C "$HOME/hermes-agent" checkout 2b31d7b283191b8069311fd3514ee89419f76516
(cd "$HOME/hermes-agent" && uv sync)

export ME3_HARNESS=hermes
export ME3_HERMES_ROOT="$HOME/hermes-agent"
export ME3_HERMES_PYTHON="$HOME/hermes-agent/.venv/bin/python"
export ME3_MODEL='YOUR_CONFIGURED_MODEL_ID'
# Optional operator/provider configuration:
# ME3_MODEL_BASE_URL, ME3_MODEL_PROVIDER, ME3_MODEL_API_KEY
```

Provide actual OpenAI-compatible inference endpoints. These are explicit base
URLs, not automatic server installers. The following are examples, not endpoints
proven available on your machine:

```sh
export ME3_ASR_BASE_URL='http://127.0.0.1:8000/v1'
export ME3_ASR_MODEL='YOUR_ASR_MODEL_ID'
export ME3_TTS_BASE_URL='http://127.0.0.1:8880/v1'
export ME3_TTS_MODEL='YOUR_TTS_MODEL_ID'
export ME3_TTS_VOICE='YOUR_VOICE_ID'
# Optional: ME3_ASR_API_KEY, ME3_TTS_API_KEY
python -m me3.duplex_voice
```

ASR must support audio transcription; TTS must support streaming mono PCM16 at
24 kHz. Whisper/MLX and Kokoro are intended inference-server choices, **not
installed or integration-qualified by this commit**. Start with headphones or an
AEC-processed microphone source. No acoustic echo cancellation is implemented.

The initial voice commands are explicit: `background task ...` delegates a draft;
`stop talking` stops foreground speech, not the job. Completed result files live
under `ME3_LOG_DIR/session-*/jobs/*/revision-*/result.md` (default log root:
`~/.local/state/me3-duplex`). Completion notices do not read the result or seize
focus. An automatic tool-routing model and spoken result retrieval are later work.

Worker tools are deliberately disabled. This baseline delegates reasoning and
drafting, not web research, shell execution, email or device control. A working
directory is not an OS sandbox. Processes start per request; persistent warmed
workers are a required latency improvement, not an existing capability.

### Pi alternative

The adapter targets the inspected current `earendil-works/pi` RPC protocol,
including `agent_settled`. An older Pi without this event/flags is not compatible.
Use an operator-installed Pi version matching the referenced source and retain
its exact version in evaluation results; no package version is silently installed.

```sh
export ME3_HARNESS=pi
export ME3_PI_BIN="$(command -v pi)"
export ME3_MODEL='YOUR_CONFIGURED_MODEL_ID'
python -m me3.duplex_voice
```

Tools, extensions, MCP, skills, templates and context-file discovery are disabled
for this baseline. Provider credentials remain in the operator's environment.
The Pi adapter is protocol-tested against fixtures, not a live provider.

## Connect the existing course benchmark

Use its unchanged launcher and scorer. Run the launcher with this project's
voice environment; run fdbench itself with its own environment.

```sh
git clone https://github.com/trueshotjames/ai231-me3-full-duplex-benchmarking.git fd-benchmark
export FDBENCH_PROJECT="$PWD"
export FDBENCH_ENTRY="$PWD/integrations/fdbench_entry.py"
python fd-benchmark/launch_assistant.py --check
python fd-benchmark/launch_assistant.py --url ws://LAPTOP-IP:8791 --once
```

The launcher supplies audio transport; it must not open a physical microphone in
benchmark mode. Input is 16 kHz; TTS/output is 24 kHz and the benchmark resamples.
`--check` validates imports/rates, **not provider connectivity or model quality**.
The same `build()` creates both local and benchmark pipelines. No labels, expected
responses, trial categories or judge outputs are supplied to the controller.

## Known limits

ASR is utterance-based; full foreground text is buffered before synthesis.
Backchannel recognition is a small exact-phrase policy, not an acoustic classifier.
Optional `ME3_LEXICAL_TURN_HOLD=1` enables a crude conjunction-ending hold experiment;
it is off by default. Proactive `Mm-hm.` responses are demonstrated through the
controller's explicit incomplete-turn input, not a learned prosodic policy.

Addressee detection, TV/bystander rejection, AEC, incremental ASR, word-accurate
heard-prefix tracking, real Pi4/M2 measurements, live Hermes/Pi provider tests and
Full-Duplex-Bench scores are **not established**. Transport start/stop receipts
are approximate whole-utterance signals, not proof of acoustic delivery. Test
chunk gaps, cancellation and delayed output events before relying on them.

The full existing test suite can be run after installing `.[test,mcp]`:
`python -m unittest discover -s tests -v`. The local implementation receipt covers
only the new overlay tests; it does not relabel old tests as rerun.
