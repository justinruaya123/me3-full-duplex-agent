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
    """Receipts must identify the exact submitted utterance."""

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
    """Bounded PCM16 queue; a provisional pause consumes no queued audio."""

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


# Finite English guard, not a general sentence tokenizer. A sentence-final
# abbreviation conservatively waits for another confirmed boundary or EOF.
_SPEECH_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "mx.", "dr.", "prof.", "sr.", "jr.", "st.",
    "mt.", "vs.", "etc.", "e.g.", "i.e.", "approx.", "dept.", "no.",
    "fig.", "inc.", "ltd.", "co.", "corp.", "ph.d.", "a.m.", "p.m.",
    "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.",
    "sept.", "oct.", "nov.", "dec.",
})


def _ends_abbreviation(text: str) -> bool:
    """Conservatively retain listed abbreviations and dotted initials."""
    if not text.endswith("."):
        return False
    word = text.rsplit(maxsplit=1)[-1].lstrip("\"'([{“‘").casefold()
    return word in _SPEECH_ABBREVIATIONS or bool(
        re.fullmatch(r"(?:[a-z]\.)+", word)
    )


async def clauses(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Confirm boundaries with whitespace; never split source words."""
    pending = ""
    async for text in stream:
        # Inspect characters in source order so delta sizes cannot change a
        # boundary or bypass the 240-character buffering limit.
        for character in text:
            if not pending and character.isspace():
                continue
            pending += character
            if character.isspace():
                chunk = pending.rstrip()
                if (
                    character == "\n" or chunk.endswith((".", "!", "?", ";"))
                ) and not _ends_abbreviation(chunk):
                    pending = ""
                    if chunk:
                        yield chunk
                    continue
            if len(pending) > 240:
                for end in range(240, 0, -1):
                    if pending[end].isspace() and not _ends_abbreviation(
                        pending[:end].rstrip()
                    ):
                        break
                else:
                    raise BufferError("Speech token exceeds clause buffer")
                chunk, pending = pending[:end].strip(), pending[end:].lstrip()
                if chunk:
                    yield chunk
    if pending.strip():
        yield pending.strip()
