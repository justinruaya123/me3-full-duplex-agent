"""Setup-time baking and bounded local playback of the pilot's Piper voice."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT / "integrations/voicechat/behavior/phrases.json"
ROOT = PROJECT / ".local/models/bmo-v1.0-voice"
PINS = {
    "bmo.onnx": "0b5a2f9e035f7798977320167f7b1bc5a5eeab4b15470d975b80fc56ae3bd8e0",
    "bmo.onnx.json": "32e87407fd1a33b1282d6ddc80cc2af58eeec86d5c004062100732a8e996ca05",
}
BASE = "https://github.com/brenpoly/be-more-agent/releases/download/v1.0-voice/"
RECIPE = "piper-1.4.2/default-speaker/default-scales/bee-mo/soxr-24k-mono-s16-v1"
MAX_FRAMES = 24000 * 5


def wake_greeting(text, phrase="", *, bare=True):
    def words(value):
        return " ".join(re.sub(r"[.,!?]", " ", value.casefold()).split())

    configured = words(phrase) or "hey bmo"
    spoken = words(text)
    if configured.replace(" ", "") not in {"heybmo", "heybeemo", "bmo", "beemo"}:
        return spoken == configured
    # The name alone is an address except when it could answer BMO's question.
    name = spoken.replace(" ", "")
    if name.startswith("hey"):
        name = name[3:]
    elif bare:
        name = name.removeprefix("a")
    else:
        return False
    return name in {"bmo", "bemo", "beemo", "bimo"}


def trim_lead(pcm):
    """Keep 20 ms before the first audible sample of a 24 kHz BMO phrase."""
    for index, sample in enumerate(memoryview(pcm).cast("h")):
        if abs(sample) >= 250:
            return pcm[2 * max(0, index - 480):]
    return pcm


def phrases():
    groups = json.loads(CATALOG.read_text())
    for name in ("wake", "listening", "setup", "waiting", "searching", "accepted", "follow_up"):
        values = groups[name]
        if not isinstance(values, list) or not 1 <= len(values) <= 12 or any(
            not isinstance(s, str) or not s.strip() or len(s) > 120 for s in values
        ):
            raise ValueError(f"Invalid BMO phrases for {name}")
    return groups


def verify(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest() == PINS[path.name]


def renderer(root):
    from importlib.metadata import version
    import numpy as np
    import soxr
    from piper import PiperVoice

    if version("piper-tts") != "1.4.2":
        raise ValueError("BMO requires piper-tts==1.4.2")
    voice = PiperVoice.load(root / "bmo.onnx", use_cuda=False)

    def render(text):
        spoken = re.sub(r"\bBMO\b", "Bee Mo", text, flags=re.IGNORECASE)
        audio = [c.audio_int16_array for c in voice.synthesize(spoken)]
        if not audio:
            raise ValueError("Piper returned empty speech")
        pcm = soxr.resample(np.concatenate(audio), voice.config.sample_rate, 24000)
        return pcm.astype("<i2").tobytes()
    return render


def clip_path(cache, text):
    key = hashlib.sha256(json.dumps([PINS, RECIPE, text], sort_keys=True).encode()).hexdigest()
    return cache / (key + ".wav")


def read_clip(cache, text):
    with wave.open(str(clip_path(cache, text)), "rb") as src:
        frames = src.getnframes()
        if ((src.getframerate(), src.getnchannels(), src.getsampwidth()) != (24000, 1, 2)
                or not 0 < frames <= MAX_FRAMES):
            raise ValueError(f"Invalid cached clip for {text!r}")
        pcm = src.readframes(frames)
        if len(pcm) != frames * 2 or not any(pcm):
            raise ValueError(f"Damaged cached clip for {text!r}")
        return pcm


def build_cache(cache, texts, render):
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    built = 0
    for text in texts:
        try:
            read_clip(cache, text)
            continue
        except (FileNotFoundError, EOFError, wave.Error, ValueError):
            pass
        try:
            with tempfile.TemporaryDirectory(dir=cache) as stage:
                tmp = Path(stage) / "clip.wav"
                pcm = render(text)
                if len(pcm) % 2 or not 0 < len(pcm) <= MAX_FRAMES * 2 or not any(pcm):
                    raise ValueError("invalid PCM")
                with wave.open(str(tmp), "wb") as dest:
                    dest.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    dest.writeframes(pcm)
                os.chmod(tmp, 0o600)
                os.replace(tmp, clip_path(cache, text))
            built += 1
        except Exception as exc:
            raise ValueError(f"Cannot bake BMO phrase {text!r}: {exc}") from exc
    return built


def setup(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in PINS:
            path = root / name
            if path.exists() and verify(path):
                continue
            with tempfile.TemporaryDirectory(dir=root) as stage:
                tmp = Path(stage) / name
                subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                                "--proto", "=https", "--max-time", "180", "-o", str(tmp),
                                BASE + name], check=True)
                if not verify(tmp):
                    raise ValueError(f"BMO asset checksum mismatch for {name}")
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
        synth = None
        def render(text):
            nonlocal synth
            if synth is None:
                synth = renderer(root)
            return synth(text)
        texts = [s for group in phrases().values() for s in group]
        built = build_cache(root / "clips", texts, render)
        print(f"BMO voice ready · {built} baked · {len(texts) - built} reused")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    setup(parser.parse_args().root)
