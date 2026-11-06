# D1 live LLM verification — November 6, 2026

Tested source: `2d8b7d25aa0f13d5a0feb16bdf1a380cb8fb551b`.
Run started at `2026-11-06T12:10:52Z` (20:10:52 Asia/Manila).

| Track | Result | Receipt |
| --- | --- | --- |
| Real foreground provider | 2/2 passed | `foreground.json` |
| Actual controller with real foreground inference; text delivery | 2/2 passed | `controller-conversation.json` |
| Real Pi worker | Prompt rejected; missing selected-provider authentication | `pi.json`, `pi-auth-diagnostic.json` |
| Installed regression suite | 120 passed; 0 failures; 0 skips | `full-suite.txt` |

Foreground timings are single-request text timings. They do not measure ASR,
TTS, acoustic latency, percentile targets or target hardware. The Pi exact
selection was verified locally before attempting the prompt; that is not a
successful provider request. No simulated worker replaced it. The selected
provider has no auth entry in ME3's isolated Pi directory. The protocol error
was `No API key found for openai-codex.` `/login` is the supported subscription
sign-in path; no billing or model fallback was applied.

## Reproduce

Load the private operator settings, then run a foreground-only request through
the production adapter. Do not print the `.env` or request headers:

```sh
cd /Users/jus/Documents/Grad/AI231/ME3
source .env
.venv313/bin/python - <<'PY'
import asyncio
import os
from me3.configuration import ForegroundConfig
from me3.foreground import ForegroundBackend

async def main():
    config = ForegroundConfig.from_env(os.environ)
    backend = ForegroundBackend(config)
    parts = [part async for part in backend.stream(
        "Reply with exactly ME3_D1_FOREGROUND_OK. "
        "Do not use tools or provide reasoning."
    )]
    answer = "".join(parts)
    assert answer.strip() == "ME3_D1_FOREGROUND_OK"
    print(config.model, answer)

asyncio.run(main())
PY
```

For Pi, authenticate in the isolated configuration and run both role probes:

```sh
./scripts/me3.sh pi
# Inside Pi: /login, then choose ChatGPT (OpenAI Codex).
./scripts/me3.sh pi --list-models sol
./scripts/me3.sh doctor --pi-rpc
./scripts/me3.sh doctor --inference
```

The combined inference doctor runs foreground before Pi and can return only a
failure receipt when Pi fails. The foreground-only command above isolates
foreground readiness. The doctor's overall readiness also includes later voice
configuration, so successful text inference does not imply voice readiness.

The regression suite does not need provider settings:

```sh
.venv313/bin/python -m unittest discover -s tests -v
```
