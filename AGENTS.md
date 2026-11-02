# ME3 agent instructions

Read README.md, docs/DUPLEX_ARCHITECTURE.md, docs/DUPLEX_STATUS.md and
.agents/skills/duplex-invariants/SKILL.md before changing behavior.

## Current authority
The 2026-11-02 request supersedes the older OnIt-only requirement: the new duplex
entrypoint uses Hermes first and permits Pi through the same backend contract.
Keep the previous OnIt modules as a baseline. Do not change the ME2 smart-speaker
VCM, its grammar, model constraints or acceptance tests.

## Invariants
- The local host owns orchestration, jobs, artifacts, MCP and action execution.
  Only model inference may be offloaded. No remote autonomous worker by stealth.
- One speaker authority. Workers cannot call TTS, seize focus or impersonate users.
- Speech cancellation, foreground cancellation and job cancellation are distinct.
- Job completion does not imply notification delivery or a topic switch.
- Fence stale results and audio by revision/epoch. Never execute unstable ASR.
- Preserve bounded queues, cancellation cleanup, errors and explicit failures.
- No implicit mock fallback. Provider absence is an error; demo is labelled.
- Tools/side effects remain disabled until allowlists and approval are tested.
  A workspace directory is not an OS sandbox.
- Secrets belong in operator environment, not code, logs, fixtures or commits.
- Audio frames do not travel through MCP; MCP is an optional control/tool facade.
- Keep the core dependency-free and Python PEP 8. Optional audio imports stay lazy.

## Verification
Write a failing behavioral test first. Run new tests and the full suite in an
installed checkout. Do not describe source inspection or fixtures as live support.

```sh
python -m unittest discover -s tests -p '*v1.py' -v
python -m me3.duplex_demo
python -m compileall -q me3 tests integrations
# In a complete checkout after installing .[test,mcp]:
python -m unittest discover -s tests -v
```

Report exact counts/skips and distinguish control simulation, provider smoke,
transport test, dataset scoring, acoustic capture and target-hardware validation.
Do not claim GPT Live/native speech-to-speech parity without matched measurements.
Update DUPLEX_STATUS, not the historical OnIt report, for the new implementation.
