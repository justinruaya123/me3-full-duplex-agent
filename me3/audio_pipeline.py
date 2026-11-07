"""Pipecat transport wiring for rolling ASR and epoch-tagged PCM playback."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from me3.capture import RollingCapture, SmartTurn, wav16
from me3.incremental import PCMBuffer, PlaybackLedger
from me3.ownership import (
    HTTPVoiceVerifier,
    OwnershipGate,
    SessionIngress,
    enroll_reference,
)


class ConfiguredSpeech:
    def __init__(self, config: dict) -> None:
        import httpx

        from me3.speech import HTTPSpeech

        clients = []
        for key in ("asr_key", "tts_key"):
            token = config[key]
            clients.append(
                httpx.AsyncClient(
                    timeout=45,
                    headers=(
                        {"Authorization": "Bearer " + token} if token else {}
                    ),
                )
            )
        self.clients = clients
        self._listening_clip: bytes | None = None
        args = (
            config["asr_base_url"].rstrip("/") + "/audio/transcriptions",
            config["tts_base_url"].rstrip("/") + "/audio/speech",
            config["asr_model"],
            config["tts_model"],
        )
        self.asr, self.tts = [
            HTTPSpeech(
                *args,
                voice=config["tts_voice"],
                client=client,
            )
            for client in clients
        ]

    async def transcribe(self, audio: bytes) -> str:
        return await self.asr.transcribe(audio)

    async def synthesize(self, text: str):
        clip = self._listening_clip
        if text == "Mm-hm." and clip is not None:
            yield clip
            return
        cached = bytearray() if text == "Mm-hm." else None
        async for pcm in self.tts.synthesize(text):
            if cached is not None:
                if len(cached) + len(pcm) <= 96000:
                    cached.extend(pcm)
                else:
                    cached = None
            yield pcm
        if cached:
            self._listening_clip = bytes(cached)

    async def close(self) -> None:
        self._listening_clip = None
        await asyncio.gather(*(client.aclose() for client in self.clients))


async def build(
    transport,
    log_dir: Path,
    *,
    runtime=None,
    profile: str | None = None,
    speech=None,
    turn_analyzer=None,
    verifier=None,
    config=None,
    on_stage=None,
):
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import (
        ErrorFrame,
        InputAudioRawFrame,
        OutputAudioRawFrame,
        TTSAudioRawFrame,
        TTSStartedFrame,
        TTSStoppedFrame,
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import WorkerRunner
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import (
        FrameDirection,
        FrameProcessor,
    )

    from me3.configuration import ForegroundConfig
    from me3.duplex_voice import settings
    from me3.foreground import ForegroundBackend
    from me3.harnesses import configured_backend
    from me3.runtime import AgentRuntime

    config = settings() if config is None else config
    profile = profile or os.environ.get("ME3_OWNERSHIP_PROFILE", "ownership")
    if profile not in {"ownership", "course"}:
        raise ValueError("Ownership profile must be ownership or course")
    wake = os.environ.get("ME3_WAKE_PHRASE", "")
    if profile == "ownership":
        if not wake:
            raise ValueError("Set ME3_WAKE_PHRASE before starting voice")
        if verifier is None:
            verifier = HTTPVoiceVerifier(
                os.environ.get("ME3_SPEAKER_BASE_URL", ""),
                os.environ.get("ME3_SPEAKER_API_KEY", ""),
            )
    owns_runtime = runtime is None
    if runtime is None:
        runtime = AgentRuntime(
            Path(log_dir) / ("runtime-" + uuid.uuid4().hex),
            configured_backend(),
            ForegroundBackend(
                ForegroundConfig.from_env(os.environ), on_stage=on_stage
            ),
        )
    owns_speech = speech is None
    speech = speech or ConfiguredSpeech(config)
    owns_turn = turn_analyzer is None
    turn_analyzer = turn_analyzer or SmartTurn()
    audio_mode = os.environ.get("ME3_AUDIO_MODE", "headphones")
    if audio_mode not in {"headphones", "speakerphone"}:
        raise ValueError("ME3_AUDIO_MODE must be headphones or speakerphone")
    echo = None
    if audio_mode == "speakerphone":
        from me3.echo import EchoFrontEnd

        echo = EchoFrontEnd(
            delay_ms=int(os.environ.get("ME3_AEC_DELAY_MS", "0"))
        )
    ledger, pcm_buffer = PlaybackLedger(), PCMBuffer()
    resumed = asyncio.Event()
    resumed.set()
    closed = muted = False
    receipt = None
    receipt_id = None
    produced = received = 0
    final_tasks: set[asyncio.Task] = set()
    failures = asyncio.Queue(maxsize=1)

    def fail(task):
        final_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            if failures.empty():
                failures.put_nowait(task.exception())

    async def stop():
        nonlocal receipt, receipt_id
        ledger.invalidate()
        pcm_buffer.flush()
        resumed.set()
        if receipt is not None and not receipt.done():
            receipt.set_result(False)
        receipt, receipt_id = None, None
        await bridge.broadcast_interruption()

    async def speak(text):
        nonlocal receipt, receipt_id, produced, received
        token = ledger.begin(text)
        context = f"{token.session_id}:{token.epoch}:{token.serial}"
        current_receipt = asyncio.get_running_loop().create_future()
        receipt, receipt_id = current_receipt, context
        produced = received = 0
        runtime.supervisor.trace(
            "speech_submitted",
            epoch=token.epoch,
            utterance=context,
            profile=profile,
        )
        try:
            await bridge.push_frame(TTSStartedFrame(context_id=context))
            async with asyncio.timeout(90):
                async for pcm in speech.synthesize(text):
                    if ledger.active != token or closed or muted:
                        return False
                    pcm_buffer.append(pcm)
                    while pcm_buffer.size:
                        await resumed.wait()
                        if ledger.active != token or closed or muted:
                            return False
                        count = min(
                            pcm_buffer.size, 960
                        )  # 20 ms @ 24kHz PCM16.
                        chunk = pcm_buffer.read(count)
                        produced += count
                        await bridge.push_frame(
                            TTSAudioRawFrame(
                                chunk,
                                sample_rate=24000,
                                num_channels=1,
                                context_id=context,
                            )
                        )
                        # Bound transport lead while capture continues.
                        await asyncio.sleep(count / 48000)
                if ledger.active != token:
                    return False
                await bridge.push_frame(TTSStoppedFrame(context_id=context))
                return await current_receipt
        finally:
            if receipt is current_receipt:
                receipt = receipt_id = None

    def observe_transcript(event):
        if on_stage:
            stage = "asr_final" if event.committed else "asr_partial"
            on_stage(stage, text=event.text)

    controller = runtime.open_session(
        speak,
        stop,
        owner="course-benchmark" if profile == "course" else None,
        on_transcript=observe_transcript,
        is_playing=lambda: (
            # TTSStarted may precede PCM; require a software transport receipt.
            ledger.active is not None
            and ledger.did_start
            and received > 0
            and not ledger.did_complete
        ),
    )
    session_id = controller.jobs.session_id
    ledger = PlaybackLedger(session_id)
    gate = OwnershipGate(session_id, wake or "course-profile")
    ingress = SessionIngress(controller, gate)
    controller.delivery_authorized = lambda: (
        profile == "course" or gate.is_active()
    )
    if profile == "ownership":
        controller.jobs.authorized = lambda: (
            not controller._closed and gate.is_active()
        )
    enrollment_owner = None
    runtime.supervisor.trace(
        "voice_profile",
        profile=profile,
        session_id=session_id,
        ownership_bypassed=profile == "course",
        audio_mode=audio_mode,
    )

    def dismiss():
        controller.user_speaking = controller.turn_open = False
        controller._idle.set()
        controller._turn_final.set()
        pcm_buffer.resume()
        resumed.set()

    def resolve_empty(generation):
        if (
            closed or muted or controller._closed or capture.closed
            or generation != capture.generation or capture.active
            or controller.user_speaking
        ):
            return
        dismiss()
        runtime.supervisor.trace(
            "empty_turn_resolved", generation=generation
        )

    def resume_backchannel(event, generation):
        if (
            closed or muted or controller._closed or controller.user_speaking
            or not capture.consume_backchannel(event, generation=generation)
        ):
            return
        pcm_buffer.resume()
        resumed.set()
        runtime.supervisor.trace(
            "provisional_backchannel_resumed", generation=capture.generation,
            turn_id=event.turn_id,
        )

    async def emit(event, pcm):
        nonlocal enrollment_owner
        if closed or muted:
            return
        generation = capture.generation
        if profile == "course":
            outcome = await controller.transcript(event, addressed=True)
            if event.committed:
                pcm_buffer.resume()
                resumed.set()
            elif outcome == "backchannel":
                resume_backchannel(event, generation)
            elif outcome == "listening":
                pcm_buffer.resume()
                resumed.set()
            return
        if gate.owner is None:
            if enrollment_owner and event.committed:
                generation = capture.generation
                if await enroll_reference(
                    gate,
                    verifier,
                    enrollment_owner,
                    pcm,
                    lambda: (
                        not closed
                        and not muted
                        and generation == capture.generation
                    ),
                ):
                    controller.jobs.owner = enrollment_owner
                    enrollment_owner = None
                    runtime.supervisor.trace(
                        "owner_enrolled", session_id=session_id
                    )
                dismiss()
            elif gate.wake(event.text):
                runtime.supervisor.trace(
                    "ownership_candidate", session_id=session_id
                )
                dismiss()
            return
        # Verification runs independently of controller/harness inference.
        evidence = await verifier.verify(gate.owner, pcm, event.text)
        if generation != capture.generation or closed or muted:
            return
        outcome = await ingress.accept(event, evidence)
        if outcome in {"unverified", "stale"}:
            if gate.closed:
                controller.jobs.owner = None
                verifier.close()
                await stop()
            dismiss()
        elif event.committed:
            pcm_buffer.resume()
            resumed.set()
        elif outcome == "backchannel":
            resume_backchannel(event, generation)
        elif outcome == "listening":
            pcm_buffer.resume()
            resumed.set()

    capture = RollingCapture(
        session_id,
        lambda pcm: speech.transcribe(wav16(pcm)),
        turn_analyzer,
        emit,
        on_empty=resolve_empty,
    )

    class EchoCleaner(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM and isinstance(
                frame, InputAudioRawFrame
            ):
                if muted or closed:
                    return
                if frame.sample_rate != 16000 or frame.num_channels != 1:
                    raise ValueError(
                        "Capture must be 16kHz mono before AEC/VAD"
                    )
                if echo is not None:
                    frame.audio = echo.capture(frame.audio)
            await self.push_frame(frame, direction)

    class Bridge(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM:
                if (
                    isinstance(frame, VADUserStartedSpeakingFrame)
                    and not muted
                ):
                    capture.begin()
                    controller.user_started()
                    pcm_buffer.pause()
                    resumed.clear()
                elif (
                    isinstance(frame, VADUserStoppedSpeakingFrame)
                    and not muted
                ):
                    controller.user_stopped()
                    task = asyncio.create_task(
                        capture.finish(generation=capture.generation)
                    )
                    final_tasks.add(task)
                    task.add_done_callback(fail)
                elif isinstance(frame, InputAudioRawFrame):
                    if frame.sample_rate != 16000 or frame.num_channels != 1:
                        raise ValueError("Runtime capture must be 16kHz mono")
                    if not muted:
                        capture.feed(frame.audio)
                        partial = capture._partial
                        if partial is not None and partial not in final_tasks:
                            final_tasks.add(partial)
                            partial.add_done_callback(fail)
                    return  # Input audio never enters the output queue.
                elif isinstance(frame, ErrorFrame):
                    await stop()
            await self.push_frame(frame, direction)

    class OutputFence(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM and isinstance(
                frame, (TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame)
            ):
                if frame.context_id != receipt_id or closed or muted:
                    return
            await self.push_frame(frame, direction)

    class ReceiptSink(FrameProcessor):
        async def process_frame(self, frame, direction):
            nonlocal received
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM:
                context = getattr(frame, "context_id", None)
                if (
                    isinstance(frame, TTSStartedFrame)
                    and context == receipt_id
                ):
                    if ledger.active:
                        ledger.started(ledger.active)
                elif isinstance(frame, OutputAudioRawFrame) and receipt_id:
                    # Transport rechunking can omit context_id. The matching
                    # final control frame remains ordered behind the audio.
                    if context is None or context == receipt_id:
                        received += len(frame.audio)
                        if echo is not None:
                            echo.played(frame.audio, frame.sample_rate)
                elif (
                    isinstance(frame, TTSStoppedFrame)
                    and context == receipt_id
                ):
                    if (
                        ledger.active
                        and produced > 0
                        and received >= produced
                        and ledger.completed(ledger.active)
                    ):
                        if receipt is not None and not receipt.done():
                            receipt.set_result(True)
                        runtime.supervisor.trace(
                            "transport_utterance_completed",
                            utterance=context,
                            bytes=received,
                            profile=profile,
                        )
            await self.push_frame(frame, direction)

    bridge = Bridge()
    # CPU development: 393 ms onset p95 over 135 synthetic speech variants.
    # Speech-noise and physical echo remain unqualified. This accelerates
    # provisional pause only; transcript/owner permission stays separate.
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.7,
            start_secs=0.096,
            stop_secs=0.2,
            min_volume=0.5,
        )
    )
    pipeline = Pipeline(
        [
            transport.input(),
            EchoCleaner(),
            VADProcessor(vad_analyzer=vad),
            bridge,
            OutputFence(),
            transport.output(),
            ReceiptSink(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
        idle_timeout_secs=None,
    )
    runner = WorkerRunner(handle_sigint=False)

    class VoiceControl:
        def __init__(self):
            self.controller = controller

        async def __call__(self):
            nonlocal closed
            closed = True
            await ingress.close()
            await stop()
            await worker.cancel()

        def enroll(self, owner: str):
            nonlocal enrollment_owner
            if profile != "ownership":
                raise RuntimeError("Course bypass cannot enroll owners")
            gate.begin_enrollment()
            enrollment_owner = owner

        async def mute(self):
            nonlocal muted
            muted = True
            gate.close()
            controller.jobs.owner = None
            if verifier:
                verifier.close()
            await capture.close()
            if echo is not None:
                echo.reset()
            await controller.close()
            await stop()
            runtime.supervisor.trace(
                "physical_control_mute", session_id=session_id
            )

    async def monitor():
        while True:
            if not failures.empty():
                raise await failures.get()
            if profile == "ownership" and not gate.is_active() and gate.closed:
                controller.jobs.owner = None
                verifier.close()
                await controller.close()
                await stop()
                await worker.cancel()
                return
            if profile == "course" or gate.is_active():
                controller.poll()
            await asyncio.sleep(0.05)

    async def run():
        pipeline_task = monitor_task = None
        try:
            await runner.add_workers(worker)
            pipeline_task = asyncio.create_task(runner.run())
            monitor_task = asyncio.create_task(monitor())
            done, _ = await asyncio.wait(
                (pipeline_task, monitor_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
        finally:
            await runtime.end_session(controller)
            gate.close()
            if verifier:
                verifier.close()
            await capture.close()
            for task in list(final_tasks):
                task.cancel()
            await asyncio.gather(*final_tasks, return_exceptions=True)
            await worker.cancel()
            for task in (pipeline_task, monitor_task):
                if task:
                    task.cancel()
            await asyncio.gather(
                *(t for t in (pipeline_task, monitor_task) if t),
                return_exceptions=True,
            )
            if owns_speech:
                await speech.close()
            if owns_turn:
                await turn_analyzer.close()
            if owns_runtime:
                # A transport disconnect ends speaking, not delegated work.
                for job in runtime.supervisor.list():
                    await runtime.supervisor.wait(job["id"])
                await runtime.close()

    return run(), VoiceControl()
