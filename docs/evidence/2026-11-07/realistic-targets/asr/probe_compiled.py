"""Private native same-model compilation probe and development speech."""
import importlib
import json
import os
import time
import wave
from pathlib import Path

import mlx.core as mx
import numpy as np
from scipy.signal import resample_poly

from me3.whisper_inference import _mel_key, request_encoder

root = Path(__file__).resolve().parents[4]
whisper = importlib.import_module('mlx_whisper.transcribe')
model_id = os.environ['ME3_ASR_MODEL']
model = whisper.ModelHolder.get_model(model_id, mx.float16)
original = model.encoder
with wave.open(str(root / 'docs/evidence/2026-11-07/d2/voice-sample.wav')) as stream:
    audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
samples = [resample_poly(audio, 2, 3)]
compiled = mx.compile(original)
trials = []
for mode in ('warm', 'baseline', 'compiled', 'baseline', 'compiled', 'compiled'):
    model.encoder = compiled if mode == 'compiled' else original
    started = time.monotonic()
    try:
        with request_encoder(model, key=_mel_key):
            result = whisper.transcribe(samples[0], path_or_hf_repo=model_id, word_timestamps=True, verbose=None)
    finally:
        model.encoder = original
    trials.append({'mode': mode, 'seconds': time.monotonic() - started, 'text': result['text'], 'language': result['language'], 'words': [w for s in result['segments'] for w in s.get('words', [])]})

report = {'passed': all('voice system is ready' in t['text'].lower() for t in trials), 'asr_model': model_id, 'tts_model': os.environ['ME3_TTS_MODEL'], 'voice': os.environ['ME3_TTS_VOICE'], 'trials': trials}
(root / '.local/verification/targets/asr/compile-native.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
