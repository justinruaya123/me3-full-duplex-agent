"""Optional Pipecat wiring; module import does not load audio models."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from me3.duplex import DuplexController, SupervisorJobs
from me3.harnesses import configured_backend

PIPECAT_REVISION = "6f777a0ef3bb98163d10d708525a0db21cda5fbf"


def settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if env is None else env
    names = ("ASR_BASE_URL", "ASR_MODEL", "TTS_BASE_URL", "TTS_MODEL",
             "TTS_VOICE")
    if any(not values.get("ME3_" + key) for key in names):
        raise ValueError(
            "Set ME3_ASR/TTS_BASE_URL, MODEL and TTS_VOICE explicitly",
        )
    result = {key.lower(): values["ME3_" + key] for key in names}
    for key in ("asr_base_url", "tts_base_url"):
        url = urlparse(result[key])
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Inference endpoints must be HTTP(S) base URLs")
    result["asr_key"] = values.get("ME3_ASR_API_KEY", "local-not-secret")
    result["tts_key"] = values.get("ME3_TTS_API_KEY", "local-not-secret")
    return result


async def build(transport, log_dir: Path):
    """Return (run coroutine, async cancel), matching fdbench's entry contract.

    The ASR service is utterance-based. This baseline does NOT claim semantic
    turn detection, AEC, addressee detection or native speech-to-speech timing.
    """
    config = settings()
    backend = configured_backend()
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame,
        TranscriptionFrame, TTSSpeakFrame, VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import WorkerRunner
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import (
        FrameDirection, FrameProcessor,
    )
    from pipecat.services.openai.stt import OpenAISTTService
    from pipecat.services.openai.tts import OpenAITTSService

    from me3.core import Supervisor

    stt = OpenAISTTService(
        api_key=config["asr_key"], base_url=config["asr_base_url"],
        settings=OpenAISTTService.Settings(model=config["asr_model"]),
    )
    tts = OpenAITTSService(
        api_key=config["tts_key"], base_url=config["tts_base_url"],
        sample_rate=24000,
        settings=OpenAITTSService.Settings(
            model=config["tts_model"], voice=config["tts_voice"],
        ),
    )
    root = Path(log_dir).resolve() / ("session-" + uuid.uuid4().hex)
    supervisor = Supervisor(root, backend)
    jobs = SupervisorJobs(supervisor)

    class Bridge(FrameProcessor):
        def __init__(self):
            super().__init__()
            self.events = asyncio.Queue(maxsize=16)
            self.playing = False
            self.receipt = None
            self.started = False
            self.controller = DuplexController(
                jobs, backend, self.speak, self.stop_speech,
                is_playing=lambda: self.playing,
            )

        async def speak(self, text):
            receipt = asyncio.get_running_loop().create_future()
            self.receipt, self.started = receipt, False
            try:
                await self.push_frame(TTSSpeakFrame(
                    text, append_to_context=False,
                ))
                # Transport events, not word-accurate or acoustic confirmation.
                return await asyncio.wait_for(receipt, 90)
            finally:
                if self.receipt is receipt:
                    self.receipt = None

        async def stop_speech(self):
            receipt, self.receipt = self.receipt, None
            self.started = self.playing = False
            if receipt is not None and not receipt.done():
                receipt.set_result(False)
            await self.broadcast_interruption()

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self.controller.user_started()
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                self.controller.user_stopped()
            elif isinstance(frame, BotStartedSpeakingFrame):
                self.playing = True
                if self.receipt is not None:
                    self.started = True
                jobs.trace("transport_bot_started")
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self.playing = False
                jobs.trace("transport_bot_stopped")
                if (self.started and self.receipt is not None
                        and not self.receipt.done()):
                    self.receipt.set_result(True)
            elif isinstance(frame, ErrorFrame):
                jobs.trace("audio_provider_error")
                if self.receipt is not None and not self.receipt.done():
                    self.receipt.set_result(False)
            elif (isinstance(frame, TranscriptionFrame)
                  and direction == FrameDirection.DOWNSTREAM):
                if frame.text.strip():
                    try:
                        self.events.put_nowait(frame.text)
                    except asyncio.QueueFull as exc:
                        raise RuntimeError("ASR queue overflow") from exc
                else:
                    jobs.trace("empty_transcript")
                return  # Never synthesize the user's transcript as bot text.
            await self.push_frame(frame, direction)

        async def consume(self):
            while True:
                text = await self.events.get()
                try:
                    # Opt-in lexical experiment, NOT a semantic endpoint model.
                    hold = os.environ.get("ME3_LEXICAL_TURN_HOLD") == "1"
                    suffix = text.lower().rstrip(" .,?!")
                    incomplete = hold and suffix.endswith(
                        (" because", " and", " but"),
                    )
                    await self.controller.accept(text, complete=not incomplete)
                finally:
                    self.events.task_done()

    bridge = Bridge()
    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=SileroVADAnalyzer()),
        stt, bridge, tts, transport.output(),
    ])
    worker = PipelineWorker(pipeline, params=PipelineParams(
        audio_in_sample_rate=16000, audio_out_sample_rate=24000,
    ))
    runner = WorkerRunner(handle_sigint=False)

    async def notices():
        while True:
            bridge.controller.poll()
            await asyncio.sleep(0.1)

    async def run():
        consumer = asyncio.create_task(bridge.consume())
        notifier = asyncio.create_task(notices())
        pipeline_run = None
        try:
            await runner.add_workers(worker)
            pipeline_run = asyncio.create_task(runner.run())
            done, _ = await asyncio.wait(
                (pipeline_run, consumer, notifier),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()  # Surface provider/control failure; never mock.
        finally:
            consumer.cancel()
            notifier.cancel()
            await bridge.controller.close()
            await worker.cancel()
            if pipeline_run is not None:
                pipeline_run.cancel()
            await asyncio.gather(
                consumer, notifier,
                *([pipeline_run] if pipeline_run is not None else []),
                return_exceptions=True,
            )
            await supervisor.close()

    async def cancel():
        await bridge.controller.close()
        await worker.cancel()

    return run(), cancel


async def _local() -> None:
    from pipecat.transports.local.audio import (
        LocalAudioTransport, LocalAudioTransportParams,
    )

    transport = LocalAudioTransport(LocalAudioTransportParams(
        audio_in_enabled=True, audio_out_enabled=True,
    ))
    run, _ = await build(
        transport,
        Path(os.environ.get("ME3_LOG_DIR", "~/.local/state/me3-duplex"))
        .expanduser(),
    )
    await run


if __name__ == "__main__":
    try:
        asyncio.run(_local())
    except KeyboardInterrupt:
        pass
