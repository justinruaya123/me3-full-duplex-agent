"""Client Kokoro synthesis. One cancellable native process per voice session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

BUNDLE = "kokoro-int8-multi-lang-v1_0"
DEFAULT_DIR = ".local/models/" + BUNDLE
VOICE = "sid-0"
PINS = {
    "model.int8.onnx": "75635ea3b85a32d00094dcdd61a258aba87c160f7c264c304a7b3ae9d734195e",
    "voices.bin": "1c5a5b983d3d50d8586d437a51f3faa2da7919ce76a013c081e65671a3447c29",
    "tokens.txt": "6ebb6bb288f20f3ae8d004d3c2ca27697da27c037d75e81a60e2a6a663f95425",
    "lexicon-us-en.txt": "7daaab53a181be9885b853a8582bf1838186317e5dadacbcef9c426d6fa0da14",
}
MAX_PCM = 8 * 1024 * 1024


def verify_assets(root: Path) -> None:
    if not (root / "espeak-ng-data").is_dir():
        raise ValueError("Install the pinned Kokoro bundle in ME3_KOKORO_DIR")
    for name, expected in PINS.items():
        with (root / name).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != expected:
                raise ValueError("Kokoro asset checksum mismatch: " + name)


def serve(root: Path) -> None:
    import numpy as np
    import sherpa_onnx as sherpa

    verify_assets(root)
    kokoro = sherpa.OfflineTtsKokoroModelConfig(
        model=str(root / "model.int8.onnx"),
        voices=str(root / "voices.bin"),
        tokens=str(root / "tokens.txt"),
        data_dir=str(root / "espeak-ng-data"),
        lexicon=str(root / "lexicon-us-en.txt"),
        lang="en-us",
    )
    model = sherpa.OfflineTtsModelConfig(kokoro=kokoro, num_threads=2, provider="cpu")
    engine = sherpa.OfflineTts(sherpa.OfflineTtsConfig(model=model))
    if engine.sample_rate != 24000:
        raise ValueError("Local Kokoro must produce 24 kHz audio")
    output = sys.stdout.buffer
    output.write(b"ready\n")
    output.flush()
    for line in sys.stdin.buffer:
        text = json.loads(line)
        audio = engine.generate(text, sid=0)
        samples = np.asarray(audio.samples)
        if (
            samples.ndim != 1
            or not 0 < samples.size <= MAX_PCM // 2
            or audio.sample_rate != 24000
            or not np.isfinite(samples).all()
        ):
            raise ValueError("Invalid local Kokoro PCM")
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        output.write(struct.pack(">I", len(pcm)))
        output.write(pcm)
        output.flush()


class LocalKokoro:
    def __init__(self, root: Path):
        self.root = root
        self.process = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.reading = None

    async def start(self):
        if self.closed:
            raise RuntimeError("Local synthesis is closed")
        if self.process is not None:
            return
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "me3.local_tts",
            str(self.root.resolve()),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={
                k: os.environ[k] for k in ("PATH", "LANG", "TMPDIR") if k in os.environ
            },
        )
        self.process = process
        try:
            if self.closed:
                raise RuntimeError("Local synthesis is closed")
            async with asyncio.timeout(45):
                if await self._read(process.stdout.readline()) != b"ready\n":
                    raise RuntimeError(
                        "Local Kokoro failed to load; check assets and client dependencies"
                    )
        except BaseException:
            await self._reap()
            raise

    async def _read(self, operation):
        self.reading = asyncio.create_task(operation)
        try:
            return await self.reading
        except asyncio.CancelledError:
            if self.closed:
                raise RuntimeError("Local synthesis is closed") from None
            raise
        finally:
            self.reading = None

    async def _reap(self):
        process, self.process = self.process, None
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            if self.reading is not None:
                reading = self.reading
                reading.cancel()
                await asyncio.gather(reading, return_exceptions=True)
            await process.communicate()

    async def synthesize(self, text: str):
        from me3.incremental import clauses

        if not text.strip() or len(text) > 16000:
            raise ValueError("TTS requires 1 to 16000 characters")

        async def source():
            yield text

        async with self.lock:
            await self.start()
            process = self.process
            total = 0
            try:
                async for clause in clauses(source()):
                    process.stdin.write(json.dumps(clause).encode() + b"\n")
                    async with asyncio.timeout(45):
                        await process.stdin.drain()
                        header = await self._read(process.stdout.readexactly(4))
                        (size,) = struct.unpack(">I", header)
                        total += size
                        if not size or size % 2 or total > MAX_PCM:
                            raise ValueError("Invalid local synthesis response length")
                        pcm = await self._read(process.stdout.readexactly(size))
                    for offset in range(0, size, 4800):
                        if self.closed:
                            raise RuntimeError("Local synthesis is closed")
                        yield pcm[offset : offset + 4800]
            except BaseException:
                await self._reap()
                raise

    async def close(self):
        self.closed = True
        await self._reap()


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
