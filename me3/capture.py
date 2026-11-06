"""Bounded rolling-window ASR. Capture never waits for inference."""

from __future__ import annotations

import asyncio
import io
import re
import wave

from me3.incremental import RollingTranscript


def wav16(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm)
    return output.getvalue()


class RollingCapture:
    def __init__(
        self,
        session_id: str,
        recognize,
        analyze,
        emit,
        *,
        max_seconds: float = 16,
        interval: float = 0.8,
    ) -> None:
        if not 0 < interval <= max_seconds <= 16:
            raise ValueError(
                "Rolling ASR requires 0 < interval <= limit <= 16s"
            )
        self.session_id = session_id
        self.recognize, self.analyze, self.emit = recognize, analyze, emit
        self.limit, self.interval = (
            int(max_seconds * 32000),
            int(interval * 32000),
        )
        self.audio = bytearray()
        self.preroll = b""
        self.active = self.committed = self.invalid = False
        self.closed = False
        self.generation = self.turn = self.total = self.start_sample = 0
        self.last_snapshot = 0
        self.rolling: RollingTranscript | None = None
        self._partial: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._pending_snapshots = 0
        self._waiting_snapshots: dict[asyncio.Task, int] = {}

    def begin(self) -> None:
        if self.closed:
            raise RuntimeError("Capture is closed")
        self.generation += 1
        if self.rolling is None or self.committed or self.invalid:
            self.turn += 1
            self.audio = bytearray(self.preroll)
            self.start_sample = max(0, self.total - len(self.preroll) // 2)
            self.rolling = RollingTranscript(self.session_id, str(self.turn))
            self.committed = self.invalid = False
            self.last_snapshot = 0
        self.active = True

    def feed(self, pcm: bytes) -> None:
        if self.closed:
            return
        if len(pcm) % 2:
            raise ValueError("Capture requires PCM16 mono at 16kHz")
        self.total += len(pcm) // 2
        self.preroll = (self.preroll + pcm)[-9600:]
        if not self.active or self.invalid:
            return
        if len(self.audio) + len(pcm) > self.limit:
            self.audio.clear()
            self.invalid = True
            self.generation += 1
            raise BufferError("ASR turn exceeds 16s; fragment discarded")
        self.audio.extend(pcm)
        if len(self.audio) - self.last_snapshot >= self.interval and (
            self._partial is None or self._partial.done()
        ):
            self.last_snapshot = len(self.audio)
            self._partial = asyncio.create_task(self._snapshot(False))

    async def _snapshot(self, final: bool) -> None:
        generation = self.generation
        # A pause can resume while native ASR still owns the lock. Retire only
        # superseded waiters; cancelling the running request would not stop its
        # native inference and must not free that capacity prematurely.
        stale = [
            task for task, revision in self._waiting_snapshots.items()
            if revision != generation
        ]
        for task in stale:
            task.cancel()
        if stale:
            await asyncio.gather(*stale, return_exceptions=True)
        if generation != self.generation or self.closed:
            return
        if self._pending_snapshots >= 2:
            self.invalid = True
            self.generation += 1
            raise BufferError(
                "ASR snapshot queue full; pending authorization discarded"
            )
        self._pending_snapshots += 1
        task = asyncio.current_task()
        self._waiting_snapshots[task] = generation
        try:
            await self._transcribe_snapshot(final)
        finally:
            self._waiting_snapshots.pop(task, None)
            self._pending_snapshots -= 1

    async def _transcribe_snapshot(self, final: bool) -> None:
        generation, rolling, pcm = (
            self.generation,
            self.rolling,
            bytes(self.audio),
        )
        if self.closed or self.invalid or rolling is None or not pcm:
            return
        async with self._lock:
            self._waiting_snapshots.pop(asyncio.current_task(), None)
            if generation != self.generation or self.committed:
                return
            async with asyncio.timeout(30):
                if final:
                    text, complete = await asyncio.gather(
                        self.recognize(pcm),
                        self.analyze(pcm),
                    )
                else:
                    text, complete = await self.recognize(pcm), False
            if generation != self.generation or self.closed:
                return
            if not isinstance(text, str) or not text.strip():
                return
            gap = re.search(
                r"\[(?:inaudible|unknown|unclear)\]|<unk>", text, re.I
            )
            committed = final and complete is True and not gap
            event = rolling.update(
                text,
                self.start_sample / 16000,
                (self.start_sample + len(pcm) // 2) / 16000,
                committed=committed,
            )
            self.committed = committed
            await self.emit(event, pcm)

    async def finish(self) -> None:
        self.active = False
        await self._snapshot(True)

    async def close(self) -> None:
        self.closed = True
        self.generation += 1
        self.audio.clear()
        self.preroll = b""
        if self._partial:
            self._partial.cancel()
            await asyncio.gather(self._partial, return_exceptions=True)


class SmartTurn:
    """Use the bundled Pipecat ONNX analyzer, never its silence timeout."""

    def __init__(self) -> None:
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
            LocalSmartTurnAnalyzerV3,
        )

        self.analyzer = LocalSmartTurnAnalyzerV3(cpu_count=1)
        self.analyzer.set_sample_rate(16000)
        self.lock = asyncio.Lock()

    async def __call__(self, pcm: bytes) -> bool:
        from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState

        async with self.lock:
            self.analyzer.clear()
            self.analyzer.append_audio(pcm, True)
            state, _ = await self.analyzer.analyze_end_of_turn()
            return state == EndOfTurnState.COMPLETE

    async def close(self) -> None:
        await self.analyzer.cleanup()
