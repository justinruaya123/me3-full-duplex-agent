"""Paced Mac-to-Parakeet transport checks using synthetic, operator-selected WAVs."""

import argparse
import asyncio
import json
import wave
from pathlib import Path

from me3.parakeet import FRAME, Stream, credential


def read_clip(path):
    import numpy as np
    import soxr

    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        if (wav.getnchannels(), wav.getsampwidth()) != (1, 2) or not 0 < wav.getnframes() <= rate * 110:
            raise ValueError("Use a mono PCM16 fixture between 0 and 110 seconds")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return soxr.resample(samples, rate, 16000).astype("<i2").tobytes()


async def probe(client, token, first, second):
    events = []

    def record(kind, **data):
        events.append(dict(type=kind, **data))

    async def play(stream, pcm, *, cancel=False):
        events.clear()
        u = await stream.begin()
        for offset in range(0, len(pcm), FRAME):
            await stream.audio(pcm[offset:offset + FRAME].ljust(FRAME, b"\0"))
        partial_before_end = u.first_partial is not None
        text = await stream.finish(cancel=cancel)
        return dict(text=text, partial_before_end=partial_before_end, id=u.id,
                    final_count=sum(e["type"] == "final" for e in events),
                    **{k: v for e in events for k, v in e.items() if k.endswith("_ms")})

    stream = Stream(client, record, token)
    try:
        await stream.connect()
        first_result = await play(stream, first)
        canceled = await play(stream, first[:FRAME * 12], cancel=True)
        next_result = await play(stream, second)
        silence = await play(stream, bytes(FRAME * 60))
        interrupted = await stream.begin()
        await stream.audio(bytes(FRAME))
    finally:
        await stream.close()
    fresh = Stream(client, record, token)
    try:
        await fresh.connect()
        reconnected = await play(fresh, second)
    finally:
        await fresh.close()
    ok = (first_result["partial_before_end"] and first_result["final_count"] == 1
          and first_result["text"] and next_result["text"] and next_result["final_count"] == 1
          and first_result["text"] != next_result["text"]
          and next_result["text"] == reconnected["text"] and reconnected["final_count"] == 1
          and silence["text"] == "" and silence["final_count"] == 1
          and canceled["text"] is None and canceled["final_count"] == 0
          and interrupted.id != reconnected["id"])
    return dict(origin="mac-round-trip", passed=bool(ok), first=first_result,
                canceled=canceled, next=next_result, silence=silence, fresh=reconnected)


async def main(args):
    import aiohttp
    async with aiohttp.ClientSession() as client:
        result = await probe(client, credential(), read_clip(args.audio), read_clip(args.second_audio))
    report = json.dumps(result, indent=2)
    if args.report:
        args.report.write_text(report + "\n")
    print(report)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--second-audio", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
