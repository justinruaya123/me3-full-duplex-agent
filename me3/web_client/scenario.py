"""Forward real evaluator callbacks to the inspector. Do not persist PCM."""

import asyncio
import json
from pathlib import Path
import sys

from integrations.spoken_behavior_eval import evaluate

last = {}


def observe(row):
    if row["event"] == "pcm":
        key = row["context"]
        if row["mono_ns"] - last.get(key, 0) < 200_000_000:
            return
        last[key] = row["mono_ns"]
    print(json.dumps(row), flush=True)


async def main():
    out = Path(sys.argv[1])
    report = {}
    await evaluate(out, report, "yeah", sys.argv[2], observe=observe, keep_audio=False)
    print(
        json.dumps(dict(event="scenario.result", checks=report["checks"])), flush=True
    )


asyncio.run(main())
