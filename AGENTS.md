# Agent instructions: preliminary full-duplex OnIt prototype

Read README.md, docs/PLAN.md, docs/STATUS.md and
.agents/skills/duplex-invariants/SKILL.md before changing behavior.

## Fixed requirements
- Use OnIt as the real agent harness. MockBackend is a labelled test simulator,
  never an implicit substitute when OnIt or a model fails.
- The Raspberry Pi owns orchestration, job scheduling, state, artifacts, MCP
  servers, device I/O and tool execution. Only model inference may be offloaded.
- Keep foreground interaction independent of long-running jobs. One speaker
  authority; workers cannot call TTS or seize conversation focus.
- Speech interruption, foreground cancellation and job cancellation are distinct.
  Never cancel a job simply because the user speaks or changes topics.
- Return job IDs promptly after persistence. Job completion is not notification
  or topic switching. Default notices are text-only and deferred while busy.
- Revision-fence every result. Never publish a cancelled or superseded result.
- No remote shell, remote autonomous agent, arbitrary model-generated executable
  commands, device actions, email transmission or other side effects in this MVP.
- Do not change the earlier smart-speaker VCM, its grammar or its acceptance tests.

## Development
- Python must follow PEP 8. Core/simulator must remain usable without installing
  model or audio dependencies. Keep modules small and imports optional.
- Add a failing test for a behavioral change; run the full suite after it passes.
- Pin and inspect an OnIt source revision. Its APIs, import shadowing and default
  tool registration require a real integration smoke test before claiming support.
- The current OnIt runner disables all default MCP tools and harness execution.
  Enabling tools requires an allowlist, an authorization boundary, tested failure
  handling and separate foreground/worker permissions, not just a prompt edit.
- Secrets only through operator environment. Do not commit .env, tokens, raw
  microphone recordings, local artifacts, provider logs or personal data.
- State is single-owner. Never run two supervisors against the same directory.
- No auto-resume/retry of interrupted jobs until idempotency is designed and tested.
- Preserve errors; no silent model, transport, or device fallback.

## Verification commands
```sh
python -m unittest discover -s tests -v
python -m me3 demo
python -m me3 benchmark --trials 20 --output /tmp/me3-new-run
python -m compileall -q me3 tests
```
Install `.[test,mcp]` to run the SDK test rather than skipping it. Real OnIt,
real ASR/TTS, mic/speaker, Pi4/Pi5 and acoustic timing each need separate evidence.
The simulator benchmark is NOT inference speed, acoustic latency or qualification.

## Next bounded increments
1. Run the pinned OnIt adapter and stdio speech path on target hardware. Capture
   exact dependency/model versions; do not describe source inspection as a run.
2. Replace process-per-turn startup with persistent isolated OnIt workers while
   preserving cancellation/revision tests. Verify model-server contention.
3. Add AEC and semantic endpointing; test backchannels, bystanders and corrections.
4. Add a bounded foreground job-routing tool facade, then safe task tools.
5. Add spoken completion arbitration and playback-prefix tracking. Until then,
   interrupted speech delivery is unknown, not the complete generated text.
6. Adapt Full-Duplex-Bench and add concurrent-job/focus tests and acoustic capture.

Keep README and STATUS honest about implemented, tested, skipped and deferred work.
