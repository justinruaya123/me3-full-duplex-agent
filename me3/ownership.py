"""Session-local ownership and strict evidence at the voice ingress boundary."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from me3.incremental import TranscriptRevision


@dataclass(frozen=True)
class VoiceEvidence:
    owner: str | None
    verified: bool
    addressed: bool | None
    mixed: bool | None


class OwnershipGate:
    def __init__(
        self,
        session_id: str,
        wake_phrase: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 300,
    ) -> None:
        if not session_id or not wake_phrase.strip() or timeout <= 0:
            raise ValueError(
                "Session, wake phrase and positive timeout required"
            )
        self.session_id, self.wake_phrase = session_id, wake_phrase.casefold()
        self.clock, self.timeout = clock, timeout
        self.owner: str | None = None
        self.candidate = self.enrolling = self.closed = False
        self.last_activity = clock()

    def wake(self, text: str) -> bool:
        if self.closed or self.owner is not None:
            return False
        if text.strip().casefold() == self.wake_phrase:
            self.candidate = True
            return True
        return False

    def begin_enrollment(self) -> None:
        if self.closed or not self.candidate or self.owner is not None:
            raise RuntimeError("Wake must open a candidate before enrollment")
        self.enrolling = True

    def enroll(self, owner: str, *, duration: float, clean: bool) -> None:
        if not self.enrolling:
            raise RuntimeError("Enrollment must be deliberately armed locally")
        if not owner.strip() or duration < 2 or not clean:
            raise ValueError("Enrollment requires >=2 seconds of clean speech")
        self.owner, self.enrolling = owner, False
        self.last_activity = self.clock()

    def is_active(self) -> bool:
        if (
            self.owner is not None
            and self.clock() - self.last_activity > self.timeout
        ):
            self.close()
        return not self.closed and self.owner is not None

    def authorize(self, evidence: VoiceEvidence) -> bool:
        allowed = (
            self.is_active()
            and evidence.owner == self.owner
            and evidence.verified is True
            and evidence.addressed is True
            and evidence.mixed is False
        )
        if allowed:
            self.last_activity = self.clock()
        return allowed

    def close(self) -> None:
        self.owner = None
        self.enrolling = self.candidate = False
        self.closed = True


class SessionIngress:
    def __init__(self, controller, ownership: OwnershipGate) -> None:
        self.controller, self.ownership = controller, ownership
        # Pin before any input arrives so an old session cannot establish itself.
        controller._transcript_session = ownership.session_id

    async def accept(
        self,
        transcript: TranscriptRevision,
        evidence: VoiceEvidence,
    ) -> str:
        if transcript.session_id != self.ownership.session_id:
            return "stale"
        if not self.ownership.authorize(evidence):
            self.controller.jobs.trace("voice_unverified")
            return "unverified"
        return await self.controller.transcript(transcript, addressed=True)

    async def close(self) -> None:
        self.ownership.close()
        await self.controller.close()


class HTTPVoiceVerifier:
    """Authenticated verifier contract; unknown overlap/addressee fails closed.

    The service compares reference/query audio independently and returns
    match, mixed and addressed booleans. No reference is persisted by ME3.
    This adapter alone is not a speaker-verification qualification result.
    """

    def __init__(self, base_url: str, api_key: str, *, client=None) -> None:
        from me3.configuration import http_url

        if not api_key:
            raise ValueError(
                "Speaker service requires explicit authentication"
            )
        self.base_url, self.api_key = http_url(base_url), api_key
        self.client = client
        self.reference: bytes | None = None

    async def _post(self, action: str, payload: dict) -> dict:
        import httpx

        if self.client is None:
            async with httpx.AsyncClient(timeout=20) as client:
                return await self._request(client, action, payload)
        return await self._request(self.client, action, payload)

    async def _request(self, client, action: str, payload: dict) -> dict:
        response = await client.post(
            self.base_url + "/" + action,
            json=payload,
            headers={"Authorization": "Bearer " + self.api_key},
        )
        response.raise_for_status()
        record = response.json()
        if not isinstance(record, dict):
            raise ValueError("Invalid speaker service response")
        return record

    async def enroll(self, pcm: bytes) -> bool:
        import base64

        if len(pcm) < 64000:
            return False
        record = await self._post(
            "enroll",
            {
                "pcm16_16000": base64.b64encode(pcm).decode("ascii"),
            },
        )
        if record.get("clean") is True and record.get("mixed") is False:
            self.reference = pcm
            return True
        return False

    async def verify(self, owner: str, pcm: bytes, text: str) -> VoiceEvidence:
        import base64

        if self.reference is None:
            return VoiceEvidence(None, False, None, None)
        record = await self._post(
            "verify",
            {
                "reference_pcm16_16000": base64.b64encode(
                    self.reference
                ).decode("ascii"),
                "query_pcm16_16000": base64.b64encode(pcm).decode("ascii"),
                "text": text,
            },
        )
        return VoiceEvidence(
            owner,
            record.get("match") is True,
            record.get("addressed"),
            record.get("mixed"),
        )

    def close(self) -> None:
        self.reference = None


async def enroll_reference(gate, verifier, owner, pcm, valid) -> bool:
    if not valid() or not gate.enrolling or gate.closed:
        return False
    accepted = await verifier.enroll(pcm)
    if not valid() or not gate.enrolling or gate.closed:
        verifier.close()
        return False
    if accepted:
        gate.enroll(owner, duration=len(pcm) / 32000, clean=True)
        return True
    return False
