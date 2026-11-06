"""Check that measurement instrumentation preserves installed VAD states."""

import asyncio
import json
from pathlib import Path

import numpy as np
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from measure_vad import CHUNK, RATE, TracedSilero, stimuli


async def run(analyzer, pcm):
    analyzer.set_sample_rate(RATE)
    try:
        return [
            (await analyzer.analyze_audio(pcm[offset:offset + CHUNK * 2])).name
            for offset in range(0, len(pcm), CHUNK * 2)
        ]
    finally:
        await analyzer.cleanup()


async def main():
    logger.remove()
    corpus, _ = stimuli([Path(".local/verification/d2/voice-sample.wav")])
    checks = []
    for stimulus in corpus:
        if stimulus.kind != "speech" or stimulus.condition != "warm_silence":
            continue
        if stimulus.gain_db not in (0, -24):
            continue
        pcm = np.round(stimulus.samples * 32768).astype("<i2").tobytes()
        pcm += b"\0" * ((-len(pcm)) % (CHUNK * 2))
        for name, start, volume in (("baseline", 0.2, 0.6),
                                    ("volume_050", 0.096, 0.5)):
            params = VADParams(start_secs=start, min_volume=volume)
            stock = await run(SileroVADAnalyzer(params=params), pcm)
            traced = await run(TracedSilero(params), pcm)
            if stock != traced:
                raise RuntimeError("Instrumentation changed VAD states")
            checks.append({
                "stimulus": stimulus.name, "setting": name,
                "chunks": len(stock), "states_identical": True,
            })
    result = {"scope": "measurement instrumentation validation", "checks": checks}
    Path(".local/verification/targets/vad/trace-validation.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
