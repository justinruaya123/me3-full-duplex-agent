"""Revisioned hypotheses and playback state; stability is not authorization."""

from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class TranscriptRevision:
    session_id: str
    turn_id: str
    revision: int
    text: str
    start: float
    end: float
    committed: bool = False
    stable_prefix: str = ""

    def __post_init__(self) -> None:
        if (
            not self.session_id
            or not self.turn_id
            or self.revision < 1
            or not 0 <= self.start <= self.end
            or len(self.text) > 16000
        ):
            raise ValueError("Invalid transcript revision")


class RollingTranscript:
    def __init__(self, session_id: str, turn_id: str) -> None:
        self.session_id, self.turn_id = session_id, turn_id
        self.previous: list[str] = []
        self.revision = 0
        self.closed = False

    def update(
        self,
        text: str,
        start: float,
        end: float,
        *,
        committed: bool = False,
    ) -> TranscriptRevision:
        if self.closed:
            raise ValueError("A committed transcript cannot be revised")
        words, stable = text.split(), []
        for before, after in zip(self.previous, words):
            if before != after:
                break
            stable.append(after)
        self.previous = words
        self.revision += 1
        self.closed = committed
        return TranscriptRevision(
            self.session_id,
            self.turn_id,
            self.revision,
            text,
            start,
            end,
            committed,
            " ".join(stable),
        )


@dataclass(frozen=True)
class PlaybackToken:
    session_id: str
    epoch: int
    serial: int


class PlaybackLedger:
    """Receipts must identify the exact submitted utterance, never the latest."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self.epoch = 0
        self.serial = 0
        self.active: PlaybackToken | None = None
        self.did_start = False
        self.did_complete = False

    def begin(self, text: str) -> PlaybackToken:
        if not text.strip():
            raise ValueError("Empty playback text")
        self.serial += 1
        self.active = PlaybackToken(self.session_id, self.epoch, self.serial)
        self.did_start = self.did_complete = False
        return self.active

    def invalidate(self) -> None:
        self.epoch += 1
        self.active = None
        self.did_start = self.did_complete = False

    def started(self, token: PlaybackToken) -> bool:
        if token != self.active:
            return False
        self.did_start = True
        return True

    def completed(self, token: PlaybackToken) -> bool:
        if token != self.active or not self.did_start:
            return False
        self.did_complete = True
        return True

    def delivered(self, token: PlaybackToken) -> bool:
        return token == self.active and self.did_complete


class PCMBuffer:
    """Bounded mono PCM16 queue; a provisional pause consumes no queued audio."""

    def __init__(self, *, max_bytes: int = 24000 * 2 * 30) -> None:
        if max_bytes < 2 or max_bytes % 2:
            raise ValueError("PCM capacity must be a positive even byte count")
        self.max_bytes = max_bytes
        self.chunks: deque[bytes] = deque()
        self.size = 0
        self.paused = False

    def append(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            raise ValueError("PCM16 must contain whole samples")
        if self.size + len(pcm) > self.max_bytes:
            raise BufferError("Playback buffer capacity exceeded")
        self.chunks.append(pcm)
        self.size += len(pcm)

    def read(self, count: int) -> bytes:
        if count < 0 or count % 2:
            raise ValueError("Read whole PCM16 samples")
        if self.paused:
            return bytes(count)
        out = bytearray()
        while self.chunks and len(out) < count:
            chunk = self.chunks.popleft()
            used = min(len(chunk), count - len(out))
            out.extend(chunk[:used])
            self.size -= used
            if used < len(chunk):
                self.chunks.appendleft(chunk[used:])
        return bytes(out) + bytes(count - len(out))

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def flush(self) -> None:
        self.chunks.clear()
        self.size = 0
        self.paused = False


async def clauses(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Bound buffering and synthesize completed clauses with backpressure."""
    pending = ""
    async for text in stream:
        pending += text
        while pending:
            match = re.search(r"[.!?;](?:\s|$)|\n", pending)
            if match:
                end = match.end()
            elif len(pending) > 240:
                end = pending.rfind(" ", 0, 240)
                if end < 1:
                    end = 240
            else:
                break
            chunk, pending = pending[:end].strip(), pending[end:].lstrip()
            if chunk:
                yield chunk
    if pending.strip():
        yield pending.strip()
