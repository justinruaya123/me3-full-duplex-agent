# Preliminary status — 2026-10-15

## Scope delivered
An executable simulator, SQLite job supervisor, independent foreground controller,
explicit focus/revision/cancellation semantics, isolated real-OnIt adapter,
optional stdio control/speech MCP services, experimental mic/energy-VAD/PCM path,
simulator benchmark, tests and agent guidance. No existing smart-speaker files or
VCM behavior are modified.

## Observed locally
- Tests ran on Linux with Python 3.13.5.
- 29 tests discovered: 28 passed, 1 explicitly skipped (MCP SDK absent).
- HTTP speech tests use httpx.MockTransport, not an actual provider.
- Process tests execute local fixture children, not OnIt.
- The deterministic demo passed.
- The simulator benchmark ran 20 trials in each of two tracks (0/1 workers).
- The build environment could not resolve GitHub or the package index through
  its shell. No OnIt, MCP SDK, sounddevice, or model was installed here.
- GitHub reads used the connected service. The attempted create_tree write was
  blocked by the tool safety check. No remote commit or preliminary branch was
  created; the original main branch remains unchanged.

## Not yet demonstrated
Real OnIt startup/inference, actual MCP SDK integration, ASR/TTS provider behavior,
microphone/speaker operation, Raspberry Pi ARM64 installation, AEC, real-time
semantic turn-taking and acoustic latency. The included workflow is a
reproducibility gate, not a claim that CI already passed.

## Deliberate minimum-scope limitations
- Tools with external effects are disabled; OnIt is used for conversation and
  drafting only. No claim of a fully capable real-world task agent yet.
- New requests spawn new OnIt processes. Model-server priority is not enforced.
- ASR is utterance-based; LLM output is buffered; TTS uses MCP pull chunks.
- Energy VAD stops on speech, including backchannels; it is not natural
  interruption classification, AEC or session-owner identification.
- Notifications are text-only; topic switching and job routing are explicit.
- Interrupted output is marked unknown, without word-level heard-prefix tracking.
- Persistence records progress/results, not a resumable model execution snapshot.
  Active work is marked interrupted after restart and never auto-replayed.
- Graceful cancellation reaps local children. Abrupt SIGKILL/power-loss orphan
  handling and remote inference cancellation acknowledgement need further work.
- Dependency ranges are provisional; produce a tested ARM64 lock before release.
