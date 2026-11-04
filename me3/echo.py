"""Playback-reference WebRTC AEC3 front end, before VAD and recognition."""

from __future__ import annotations

from me3.incremental import PCMBuffer


class EchoFrontEnd:
    def __init__(
        self,
        *,
        processor=None,
        delay_ms: int = 0,
        max_reference_seconds: float = 2,
    ) -> None:
        if not 0 <= delay_ms <= 500 or max_reference_seconds <= 0:
            raise ValueError("Invalid AEC delay/reference capacity")
        if processor is None:
            from pywebrtc_audio import AudioProcessor

            processor = AudioProcessor(
                sample_rate=16000,
                num_channels=1,
                echo_cancellation=True,
                noise_suppression=True,
                stream_delay_ms=delay_ms,
            )
        self.processor = processor
        self.reference = PCMBuffer(
            max_bytes=int(32000 * max_reference_seconds)
        )

    def played(self, pcm: bytes, sample_rate: int) -> None:
        import numpy as np
        import soxr

        if sample_rate != 24000 or len(pcm) % 2:
            raise ValueError("AEC reference must be 24kHz mono PCM16")
        reference = np.frombuffer(pcm, dtype="<i2")
        far = soxr.resample(reference, 24000, 16000).astype("<i2").tobytes()
        self.reference.append(far)

    def capture(self, pcm: bytes) -> bytes:
        import numpy as np

        if len(pcm) % 2:
            raise ValueError("AEC capture must contain whole PCM16 samples")
        near = np.frombuffer(pcm, dtype="<i2")
        far = np.frombuffer(self.reference.read(len(pcm)), dtype="<i2")
        clean = self.processor.process(near, far)
        if clean.shape != near.shape or clean.dtype != near.dtype:
            raise ValueError("AEC changed the capture format")
        return clean.tobytes()

    def reset(self) -> None:
        self.reference.flush()
        self.processor.reset()
