"""Assistant-as-listener probes. Only the evaluator sees the pause annotations."""
import json

SR = 16000
SCENARIOS = [
    ("story", "the tricky part about moving our weekly meeting was that once we",
     "found a free afternoon everyone could finally attend", True),
    ("story_with_place", "when we got to Manila the first thing we decided to",
     "do was walk over to the old library", True),
    ("verbatim", "please take this down exactly as I say it the first line is",
     "the package will arrive at the station tomorrow morning", False),
]


async def make_clips(path, model):
    import numpy as np
    import soundfile as sf
    import soxr
    from me3.local_tts import LocalBmo

    path.mkdir()
    windows = {}
    engine = LocalBmo(model)

    async def speech(text):
        pcm = b"".join([chunk async for chunk in engine.synthesize(text)])
        samples = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
        live = np.flatnonzero(abs(samples) > .004)
        if len(live) == 0:
            raise ValueError("Piper produced silent test input")
        samples = samples[max(0, live[0] - 480):live[-1] + 481]
        return soxr.resample(samples, 24000, SR)

    try:
        for name, prefix, suffix, expected in SCENARIOS:
            first = await speech(prefix)
            last = await speech(suffix)
            start = len(first) / SR
            gap = 1.5
            signal = np.concatenate((first, np.zeros(int(SR * gap)), last))
            sf.write(path / (name + ".wav"), signal, SR, subtype="PCM_16")
            (path / (name + ".txt")).write_text(prefix + " " + suffix)
            windows["own_" + name] = {"expected": expected, "start": start, "end": start + gap}
    finally:
        await engine.close()
    return windows


def cue_peak(samples, ref, start, end):
    """Start time of a complete reference waveform whose onset is inside the gap."""
    import numpy as np

    lo, hi = max(0, round(start * SR)), round(end * SR)
    window = samples[lo:hi + len(ref) - 1]
    if len(window) < len(ref):
        return None
    size = 1 << (len(window) + len(ref) - 2).bit_length()
    spectrum = np.fft.rfft(window, size) * np.fft.rfft(ref[::-1], size)
    correlations = np.fft.irfft(spectrum, size)[len(ref) - 1:len(window)]
    energy = np.concatenate(([0.], np.cumsum(window.astype(float) ** 2)))
    energy = energy[len(ref):] - energy[:-len(ref)]
    norm = np.sqrt(np.maximum(energy * np.dot(ref, ref), 1.e-12))
    scores = correlations / norm
    i = int(np.argmax(scores))
    if scores[i] >= .80 and energy[i] >= .001 * np.dot(ref, ref):
        return (lo + i) / SR
    return None


def score_windows(run, windows, model):
    import numpy as np
    import soundfile as sf
    import soxr

    from me3 import bmo
    from me3.parakeet_voice import trim_cue_lead

    references = []
    for phrase in bmo.phrases()["listening"]:
        pcm = trim_cue_lead(bmo.read_clip(model / "clips", phrase))
        raw = np.frombuffer(pcm, dtype="<i2").astype(float) / 32768
        samples = soxr.resample(raw, 24000, SR)
        active = np.flatnonzero(abs(samples) > .005)
        references.append(samples[active[0]:active[-1] + 1])
    rows = {name: dict(case=name, **labels, observed=None, status="missing recording")
            for name, labels in windows.items()}
    for timing in sorted(run.glob("trials/*/timing.json")):
        trial = json.loads(timing.read_text())
        row = rows.get(trial.get("clip"))
        if row is None or not timing.with_name("her.flac").is_file():
            continue
        pcm, rate = sf.read(timing.with_name("her.flac"))
        if rate != SR or pcm.ndim != 1:
            raise ValueError("Expected a mono 16 kHz fdbench output recording")
        onset = next(e["t"] for e in trial["events"] if e["name"] == "first")
        start, end = onset + row["start"], onset + row["end"]
        if len(pcm) < round(end * SR):
            row["status"] = "short recording"
            continue
        matches = [cue_peak(pcm, ref, start, end) for ref in references]
        hit = min((t for t in matches if t is not None), default=None)
        row.update(status="measured", observed=hit is not None,
                   gap_to_cue_ms=round((hit - start) * 1000) if hit is not None else None,
                   gap_peak_dbfs=round(20 * np.log10(max(1e-6, max(abs(
                       pcm[round(start * SR):round(end * SR)])))), 1))
    return list(rows.values())
