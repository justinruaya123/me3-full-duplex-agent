# ME3: preliminary full-duplex OnIt agent

**Target branch: `preliminary`. Experimental, single-user, Linux/macOS prototype.**

This implements the smallest useful slice of the proposed architecture: a
foreground conversation can continue while an independent background job runs.
Stopping a reply does not stop the job; completed jobs do not seize conversation
focus. The Pi owns execution and state. Only model inference may be remote.

## Start here: no credentials or dependencies

Use Python 3.11 or newer from this repository's root:

```sh
python -m me3 demo
python -m me3 chat
```

Both commands default to an explicitly labelled **simulator**, not OnIt or a
speech model. `demo` runs its assertions and removes its temporary state on exit.
To retain the demo's artifact and traces, supply a new `--state DIRECTORY`.

In `chat`, try:

```text
/task Write a short explanation of recurrent neural networks.
Explain what a hidden state represents.
/stop
/jobs
```

The task survives `/stop`. Use the printed full job ID with `/focus ID`,
`/result ID`, `/update ID NEW REQUEST`, or `/cancel ID`. `/focus` clears focus.
`/quit` shuts down cleanly. Completion notices are **text-only** and do not change
focus. Job routing is explicit; the prototype does not infer arbitrary delegation
or context-switching language from a conversation.

Persistent state defaults to `~/.local/state/me3`. It contains SQLite job state,
per-job/revision artifacts, foreground workspaces and monotonic event traces.
Only one supervisor may own a state directory. Unfinished jobs become
`interrupted` after restart; they are not silently replayed.

## What is implemented

- Independent asynchronous foreground and bounded background queue.
- SQLite job records, isolated revision directories, atomic artifact publication,
  stale-result rejection, explicit cancellation and single-owner state locking.
- A local subprocess adapter invoking the real `OnIt.process_task` API from a
  pinned source checkout. Each foreground request/job gets its own process.
- Pi-hosted **control MCP** and **speech MCP** servers using the official SDK over
  stdio. No public listener, shared credentials in code, or hand-written MCP.
- Optional continuous local microphone capture, elementary energy VAD and
  interruptible PCM playback. The live path invokes the speech MCP server for
  ASR and TTS; the server owns the inference API calls.
- A simulator control-path benchmark, tests and repository agent instructions.

## Real OnIt: opt-in, separate environment

Install the core application in one environment. Install OnIt from its pinned
source in a **separate Python 3.12 environment on the Pi**. OnIt's dependencies
and import layout should not be mixed with the core runtime accidentally.

```sh
# In this repository
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,mcp]'

# In another directory; use an available Python 3.12 interpreter
# Installing model weights on the Pi is not required.
git clone https://github.com/sibyl-oracles/onit.git "$HOME/onit"
git -C "$HOME/onit" checkout 0a9c391560a7767f36fd56ddbe81749b44b54fec
python3.12 -m venv "$HOME/onit/.venv"
"$HOME/onit/.venv/bin/python" -m pip install -e "$HOME/onit[all]"
```

Copy `config.example.toml` **outside the repository**, for example to
`~/.config/me3.toml`. Set `backend = "onit"`, the absolute OnIt checkout/interpreter
paths, and a real model host and model identifier. All placeholder identifiers
must be replaced. Supply a provider key through `ME3_MODEL_API_KEY` if needed.
Then run:

```sh
python -m me3 chat --config ~/.config/me3.toml
```

The adapter checks the configured source commit and fails rather than falling
back to a simulator. It disables OnIt's default shell/network MCP tools and
harness code execution. This first slice supports conversation and drafting;
**it does not execute real-world side effects or research the web**. A configured
working directory is not an OS sandbox. Adding tools requires a separate,
tested authorization boundary.

Process-per-request startup is intentional for initial isolation, not a low-
latency final design. Persistent OnIt workers and measured model-server priority
are subsequent steps. Merely having two local processes does not reserve model
inference capacity on a shared Mac/GPU.

## Speech experiment: optional, not yet hardware-validated

On the Pi, install the audio dependency and OS PortAudio library:

```sh
sudo apt-get install libportaudio2
python -m pip install -e '.[speech]'
python -m sounddevice
python -m me3 voice --config ~/.config/me3.toml
```

Configure the actual input/output device names or indices in `[audio]`.
**Start with headphones or an explicitly AEC-processed microphone source.**
This repository does not install or configure acoustic echo cancellation.
The energy detector will otherwise mistake the agent's own speech or bystanders
for interruptions. It is not semantic endpointing or speaker identification.

Required inference endpoint contracts (operator-configured, never chosen by
spoken input):

| Operation | Request | Response |
| --- | --- | --- |
| ASR | Multipart POST with `file` (mono PCM16, 16 kHz WAV) and `model` | JSON with nonempty `text` |
| TTS | JSON POST with `model`, `input`, `voice`, `response_format="pcm"` | Streaming mono, little-endian PCM16 at exactly 24 kHz |

These can run on a Mac/LAN inference server or a commercial endpoint supporting
those exact contracts. No model-server installation is included. Keep HTTP on a
trusted private network; use authenticated TLS on untrusted links. Credentials
use `ME3_SPEECH_API_KEY` and are not sent to unrelated endpoints.

ASR is **utterance-based**, not incremental streaming: 20 ms input frames,
60 ms speech-start qualification, 200 ms pre-roll and 600 ms end silence. Capture
continues during generation/playback. Capture gaps and overlong speech are
discarded until silence rather than executed as partial commands. TTS is pulled
through MCP in up-to-100 ms chunks and played in 20 ms writes. This pull transport
is deliberately simple and adds overhead; it is not the final audio transport.
The entire OnIt text answer is currently obtained before synthesis begins.

Say `background task ...` to submit explicit work, or `stop talking` to stop a
reply. Those are prototype control phrases, not an intelligent language router.
Completion notices remain on the terminal. Interrupted response delivery is
recorded as unknown; word-accurate playback-prefix tracking is not implemented.
Ctrl+C ends the voice session and interrupts unfinished local jobs.

## MCP entry points

```sh
# Owns a distinct job store; do not reuse an active chat/voice store.
python -m me3 mcp --state /tmp/me3-mcp --config ~/.config/me3.toml

# Used automatically by the voice client; configuration must name real endpoints.
python -m me3 mcp-speech --config ~/.config/me3.toml
```

Control tools: `submit_job`, `get_job`, `list_jobs`, `revise_job`, `cancel_job`,
`get_result`, `set_focus`, `ask`, `stop_speaking`.
Speech tools: `transcribe`, `tts_open`, `tts_next`, `tts_cancel`.
The control server is a standalone interface, not a second supervisor attached
to the chat process. Connecting an OnIt foreground tool facade to it is deferred.
Speech tools are called by the runtime, not selected by an LLM.

## Tests and benchmark

```sh
python -m pip install -e '.[test,mcp]'
python -m unittest discover -s tests -v
python -m me3 benchmark --trials 20 --output /tmp/me3-benchmark-new
python -m compileall -q me3 tests
```

The optional SDK test exercises a real stdio server when installed. The simulator
benchmark compares request-to-text timing with zero versus one artificially
blocked worker. It writes immutable `metrics.json`, `trials.jsonl` and event
traces, includes failure denominators and source hashes, and labels itself
**not hardware qualified**. It is not ASR/LLM/TTS speed, acoustic latency or
Full-Duplex-Bench performance. See [benchmark protocol](docs/BENCHMARK.md) and
[observed status](docs/STATUS.md).

## Architecture boundaries and next work

`core.py` owns state and interaction; `backends.py`/`onit_runner.py` isolate OnIt;
`speech.py`, `mcp_server.py` and `voice.py` form the experimental audio path.
`AGENTS.md` and `.agents/skills/duplex-invariants/SKILL.md` preserve those boundaries.

Next: validate real OnIt and speech on hardware, add persistent workers and
inference priority, AEC and semantic turn-taking, bounded LLM job routing,
spoken notification arbitration, then safe action tools and acoustic evaluation.
Do not claim natural full-duplex or human-testing readiness from this baseline.

## Primary references

- Pinned OnIt API example: https://github.com/sibyl-oracles/onit/blob/0a9c391560a7767f36fd56ddbe81749b44b54fec/benchmarks/onit_provider.py
- MCP Python SDK v1 maintenance line: https://py.sdk.modelcontextprotocol.io/v1/
- Full-Duplex-Bench original paper: https://arxiv.org/abs/2503.04721
- Benchmark code: https://github.com/DanielLin94144/Full-Duplex-Bench
