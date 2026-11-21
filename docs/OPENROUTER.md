# OpenRouter foreground and Pi.dev worker

Set these values in the private environment used by the client host. Add the operator's OpenRouter credential as `OPENROUTER_API_KEY`.

```sh
ME3_FOREGROUND_PROFILE=openrouter
ME3_FOREGROUND_BASE_URL=https://openrouter.ai/api/v1
ME3_FOREGROUND_PROVIDER=google-ai-studio
ME3_FOREGROUND_MODEL=google/gemini-2.5-flash-lite
ME3_HARNESS=pi
ME3_WORKER_PROVIDER=openrouter
ME3_WORKER_MODEL=openai/gpt-oss-120b
```

The foreground sends `reasoning.effort=none`, requires supported parameters, and selects Google AI Studio exclusively. It checks model and serving provider on each response event. A separate classification request receives only the current accepted turn for supported action phrases. The controller matches the proposed kind and verbatim argument against the full explicit owner request, then rechecks the session, owner, turn, and any referenced job revision. For example, “Please delegate a task to draft the syllabus” admits the task “draft the syllabus.” “Please remember that I collect maps” admits a private note. Public fields require an explicit public-profile instruction. Invalid or ambiguous proposals produce a clarification.

Pi.dev runs locally with tools disabled. Every job revision gets a fresh worker process and a private Pi session journal in its revision directory. The worker can reuse that process within the same revision. Revising a task rebuilds the inference context from the current authorized snapshot. Earlier journals remain separate local harness records under the memory deletion policy. The worker constructs a temporary Pi configuration with an exact model override and `openRouterRouting`. `--offline` keeps Pi's catalog discovery local. The selected inference request still goes to OpenRouter. The worker checks RPC state, requires successful settlement, then checks the response's generation ID against OpenRouter's generation endpoint. A routing, model, cancellation, or completion mismatch fails the job. Only final text blocks enter the result. Operator login and existing Pi settings remain in their own directories.

These settings are the handoff defaults. For a different supported model, pin
the model ID, OpenRouter routing slug and expected response display name for
that role in the client environment. A direct HTTP worker can use the same
OpenRouter pin. See [independent LLM role selection](SETUP.md#choose-the-two-llm-roles).

With the configured account, run:

```sh
./scripts/me3.sh doctor --pi-rpc
./scripts/me3.sh doctor --inference
```

The second command requests streamed foreground text, a foreground lookup proposal, and settled worker output. It reports verified serving providers. The proposal probe does not execute a lookup. The local transport test covers the pinned Pi version and captures its emitted request body against a fixture endpoint. No authenticated OpenRouter key was available during the November 18 implementation run. The public catalog and local fixture check are recorded in the [provider evidence](evidence/2026-11-18/openrouter.json).
