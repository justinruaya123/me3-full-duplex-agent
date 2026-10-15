# Preliminary implementation plan

## Scope
Implement the approved OnIt foreground/background split as a small, single-user
Python prototype. The Raspberry Pi owns orchestration, job state, artifacts and
speech control. Only model inference may be remote. Default execution is an
explicit simulator; no credentials, downloads, microphone or external actions.

## Delivery sequence
1. Write failing tests for independent jobs, speech-only interruption, stale
   revisions, restart recovery, single-supervisor ownership and deferred notices.
2. Implement SQLite job state, isolated task workspaces and a foreground controller.
3. Add a separately installed, pinned OnIt subprocess adapter. No shared mutable
   OnIt instance; disable tool defaults and side effects for this first version.
4. Add optional inference-only HTTP ASR/TTS, local microphone energy VAD and PCM
   playback. Use utterance-based ASR initially; do not claim semantic endpointing,
   echo cancellation or fully streaming ASR/LLM.
5. Expose shared runtime operations with the official MCP SDK over stdio. Include
   an optional real SDK integration test, not a hand-written protocol substitute.
6. Add simulator demo, trace benchmark, setup instructions, AGENTS.md and a focused
   repository skill. Run local tests and verify the exact committed file hashes.

## Review focus
Cancellation before a worker starts; stale results after a task update; input
while a response is pending; failed model calls; two supervisors sharing state;
unsafe paths; bounded microphone queues; shutdown and restart without replaying
side effects; optional dependencies unavailable in the build environment.

## Rulings
- The user explicitly requested implementation on preliminary after the design
  discussion. Execute this minimum scope now without another approval round.
- Notifications default to text at idle boundaries, without automatic topic
  changes. Automatic spoken completion announcements are deferred.
- Real OnIt and audio/MCP dependencies are opt-in. Never silently switch to mocks.
- Tools with external effects and autonomous job routing are deferred. Explicit
  console/MCP job operations establish scheduler correctness first.
