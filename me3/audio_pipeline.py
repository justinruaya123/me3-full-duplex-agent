"""Pipecat transport wiring for rolling ASR and epoch-tagged PCM playback."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, aclosing
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

        def client(token):
            return httpx.AsyncClient(
                timeout=45,
                headers={"Authorization": "Bearer " + token} if token else {},
            )

        self._listening_clip = None
        self.local = None
        self.clients = [client(config["asr_key"])]
        self.asr = HTTPSpeech(
            config["asr_base_url"].rstrip("/") + "/audio/transcriptions",
            None, config["asr_model"], "", client=self.clients[0],
        )
        if config["tts_backend"] == "local":
            from me3.local_tts import LocalKokoro

            self.local = LocalKokoro(Path(config["tts_model_dir"]))
            self.tts = self.local
        else:
            self.clients.append(client(config["tts_key"]))
            self.tts = HTTPSpeech(
                None, config["tts_base_url"].rstrip("/") + "/audio/speech",
                "", config["tts_model"], voice=config["tts_voice"],
                client=self.clients[-1],
            )

    async def start(self):
        if self.local:
            await self.local.start()

    async def transcribe(self, audio: bytes) -> str:
        return await self.asr.transcribe(audio)

    async def synthesize(self, text: str):
        clip = self._listening_clip
        if text == "I’m listening." and clip is not None:
            yield clip
            return
        cached = bytearray() if text == "I’m listening." else None
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
        if self.local:
            await self.local.close()
        await asyncio.gather(*(client.aclose() for client in self.clients))


async def build(
    transport,
    log_dir: Path,
    *,
    runtime=None,
    profile: str | None = None,
    terminal_demo_owner=None,
    local_mcp=False,
    speech=None,
    turn_analyzer=None,
    verifier=None,
    config=None,
    on_stage=None,
    on_voice=None,
):
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import (
        ErrorFrame,
        InputAudioRawFrame,
        OutputAudioRawFrame,
        StartFrame,
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

    from me3.duplex_voice import settings
    from me3.foreground import configured_foreground
    from me3.harnesses import configured_backend
    from me3.runtime import AgentRuntime

    config = settings() if config is None else config
    profile = profile or "ownership"
    if profile not in {"ownership", "course", "terminal-demo"}:
        raise ValueError("Unknown voice ownership profile")
    if (profile == "terminal-demo") != bool(terminal_demo_owner):
        raise ValueError("Terminal demo requires a locally selected owner")
    trusted_demo = profile in {"course", "terminal-demo"}
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
            configured_foreground(on_stage=on_stage),
        )
    owns_speech = speech is None
    native_speech = speech = speech or ConfiguredSpeech(config)
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

    def voice(kind, **fields):
        if on_voice:
            on_voice(kind, session_id=session_id, **fields)

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
        voice("speech_script", utterance=context, text=text)
        outcome = "speech_interrupted"
        runtime.supervisor.trace(
            "speech_submitted",
            epoch=token.epoch,
            utterance=context,
            profile=profile,
        )
        try:
            await bridge.push_frame(TTSStartedFrame(context_id=context))
            async with asyncio.timeout(90), aclosing(speech.synthesize(text)) as stream:
                async for pcm in stream:
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
        except Exception:
            outcome = "speech_failed"
            raise
        finally:
            if (
                current_receipt.done()
                and not current_receipt.cancelled()
                and current_receipt.result()
            ):
                outcome = "speech_complete"
            voice(outcome, utterance=context)
            if receipt is current_receipt:
                receipt = receipt_id = None

    def observe_transcript(event):
        stage = "asr_final" if event.committed else "asr_partial"
        voice(
            stage, turn_id=event.turn_id, revision=event.revision,
            text=event.text,
        )
        if on_stage:
            on_stage(stage, text=event.text)

    controller = runtime.open_session(
        speak,
        stop,
        owner="course-benchmark" if profile == "course" else terminal_demo_owner,
        remember=profile != "course",
        on_transcript=observe_transcript,
        is_playing=lambda: (
            # TTSStarted may precede PCM; require a software transport receipt.
            ledger.active is not None
            and ledger.did_start
            and received > 0
            and not ledger.did_complete
        ),
    )
    if local_mcp:
        from me3.course_mcp import CourseMCP

        def trace_tool(tool, **fields):
            runtime.supervisor.trace("mcp_tool", tool=tool, **fields)
        speech = CourseMCP(native_speech, controller, trace_tool)
        controller.task_tools = speech.task
    controller.web_enabled = profile != "course"
    def companion(text):
        if on_voice:
            voice("companion", text=text)
        else:
            print(text, flush=True)

    controller.companion = companion
    session_id = controller.jobs.session_id
    ledger = PlaybackLedger(session_id)
    gate = OwnershipGate(session_id, wake or "course-profile")
    ingress = SessionIngress(controller, gate)
    controller.delivery_authorized = lambda: (
        trusted_demo or gate.is_active()
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
        ownership_bypassed=trusted_demo,
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
        voice("asr_backchannel", turn_id=event.turn_id, revision=event.revision,
              text=event.text)
        runtime.supervisor.trace(
            "provisional_backchannel_resumed", generation=capture.generation,
            turn_id=event.turn_id,
        )

    async def emit(event, pcm):
        nonlocal enrollment_owner
        if closed or muted:
            return
        generation = capture.generation
        if trusted_demo:
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
        peak = 0
        next_meter_at = 0.0

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
                if on_voice and frame.audio:
                    samples = memoryview(frame.audio).cast("h")
                    self.peak = max(self.peak, max(samples), -min(samples))
                    now = asyncio.get_running_loop().time()
                    if now >= self.next_meter_at:
                        voice("mic_level", peak=self.peak)
                        self.peak = 0
                        self.next_meter_at = now + 0.125
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
                    if profile == "terminal-demo":
                        await controller.course_barge_in()
                    else:
                        controller.user_started()
                    pcm_buffer.pause()
                    resumed.clear()
                elif (
                    isinstance(frame, VADUserStoppedSpeakingFrame)
                    and not muted
                ):
                    final = capture.end_vad_segment()
                    if final is not None:
                        controller.user_stopped()
                        task = asyncio.create_task(final)
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
                if isinstance(frame, StartFrame) and not muted and not closed:
                    voice("voice_open")
                elif (
                    isinstance(frame, TTSStartedFrame)
                    and context == receipt_id
                ):
                    if ledger.active:
                        ledger.started(ledger.active)
                elif isinstance(frame, OutputAudioRawFrame) and receipt_id:
                    # Transport rechunking can omit context_id. The matching
                    # final control frame remains ordered behind the audio.
                    if context is None or context == receipt_id:
                        if not received and frame.audio:
                            voice("speech_audio", utterance=receipt_id)
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
            voice("voice_closed")
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
            if trusted_demo or gate.is_active():
                controller.poll()
            await asyncio.sleep(0.05)

    async def run():
        pipeline_task = monitor_task = None
        mcp_stack = AsyncExitStack()
        try:
            if owns_speech:
                await native_speech.start()
            if local_mcp:
                await mcp_stack.enter_async_context(speech.connect())
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
            voice("voice_closed")
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
            await mcp_stack.aclose()
            if owns_speech:
                await native_speech.close()
            if owns_turn:
                await turn_analyzer.close()
            if owns_runtime:
                # A transport disconnect ends speaking, not delegated work.
                for job in runtime.supervisor.list():
                    await runtime.supervisor.wait(job["id"])
                await runtime.close()

    return run(), VoiceControl()
