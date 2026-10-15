"""
Opt-in local microphone experiment; use a headset or an AEC-processed input.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from .mcp_server import MCPSpeech
from .speech import EnergyVAD


async def voice_session(controller, config: dict, config_path: Path) -> None:
    import sounddevice as sd
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "me3", "mcp-speech", "--config", str(
            config_path.resolve(),
        )],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _listen(controller, config, MCPSpeech(session), sd)


async def _listen(controller, config, speech, sd) -> None:
    audio = config.get("audio", {})
    vad = EnergyVAD(threshold=float(audio.get("energy_threshold", 600)))
    loop = asyncio.get_running_loop()
    frames = asyncio.Queue(maxsize=50)
    dropped = False
    pending = None
    tasks = set()

    def offer(frame: bytes, fault: bool) -> None:
        nonlocal dropped
        if frames.full():
            dropped = True
        else:
            frames.put_nowait((frame, fault))

    def capture(indata, frame_count, time_info, status) -> None:
        loop.call_soon_threadsafe(offer, bytes(indata), bool(status))

    with sd.RawInputStream(
        samplerate=16000, channels=1, dtype="int16", blocksize=320,
        device=audio.get("input_device"), callback=capture,
    ), sd.RawOutputStream(
        samplerate=24000, channels=1, dtype="int16", blocksize=480,
        device=audio.get("output_device"), latency="low",
    ) as output:
        playback_lock = asyncio.Lock()

        async def speak(text: str) -> None:
            async with playback_lock:
                try:
                    async for chunk in speech.synthesize(text):
                        for offset in range(0, len(chunk), 960):
                            # Cancellation waits for at most the current
                            # driver write;
                            # no concurrent write is allowed to survive the
                            # lock.
                            write = asyncio.create_task(asyncio.to_thread(
                                output.write, chunk[offset:offset + 960]
                            ))
                            try:
                                await asyncio.shield(write)
                            except asyncio.CancelledError:
                                await write
                                raise
                except asyncio.CancelledError:
                    output.abort()
                    output.start()
                    raise

        controller.speaker = speak

        async def recognize(clip: bytes, epoch: int) -> None:
            try:
                text = await speech.transcribe(clip)
                if epoch != controller.epoch:
                    return
                print("USER:", text, flush=True)
                # Explicit preliminary commands, not natural-language task
                # routing.
                if text.lower().strip(" .!") == "stop talking":
                    controller.interrupt()
                elif text.lower().startswith("background task "):
                    job = controller.supervisor.submit(
                        text[len("background task "):],
                    )
                    print("JOB:", job["id"], flush=True)
                else:
                    answer = await controller.ask(text)
                    print("ASSISTANT:", answer, flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(
                    "VOICE ERROR:",
                    type(exc).__name__,
                    str(exc),
                    file=sys.stderr,
                )

        print(
            (
                "Listening. Ctrl+C ends the session. "
                "Completion notices are text-only."
            ),
        )
        try:
            while True:
                frame, fault = await frames.get()
                if fault or dropped:
                    dropped = False
                    while not frames.empty():
                        frames.get_nowait()
                    vad.reset()
                    # Require silence before accepting another turn.
                    vad.overflowed = True
                    controller.interrupt()
                    controller.user_speaking = False
                    if pending:
                        pending.cancel()
                    controller.supervisor.trace("capture_gap_rejected")
                    continue
                started, clip = vad.feed(frame)
                if started:
                    controller.interrupt()
                    if pending:
                        pending.cancel()
                controller.user_speaking = vad.active or vad.overflowed
                if clip:
                    pending = asyncio.create_task(
                        recognize(clip, controller.epoch),
                    )
                    tasks.add(pending)
                    pending.add_done_callback(tasks.discard)
                if pending is None or pending.done():
                    for job in controller.notices():
                        print(
                            "READY (no topic switch):",
                            job["id"],
                            flush=True,
                        )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            controller.speaker = None
