"""Development-only canonical decode input for automatic language inference."""
import importlib
import json
import os
import time
import wave
from contextlib import redirect_stdout
from pathlib import Path
import sys

import mlx.core as mx
import numpy as np
from scipy.signal import resample_poly

from me3.whisper_inference import _mel_key, request_encoder

root = Path(__file__).resolve().parents[4]
whisper = importlib.import_module('mlx_whisper.transcribe')
audio_lib = importlib.import_module('mlx_whisper.audio')
model_id = os.environ['ME3_ASR_MODEL']
model = whisper.ModelHolder.get_model(model_id, mx.float16)
original = model.encoder
compiled = mx.compile(original)

def load(path):
    with wave.open(str(path)) as stream:
        rate = stream.getframerate()
        value = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    return resample_poly(value, 16000, rate).astype(np.float32)

inputs = [('ready', load(root / 'docs/evidence/2026-11-07/d2/voice-sample.wav'))]
for item in json.loads((root / '.local/verification/targets/vad/development-speech/receipt.json').read_text())['files']:
    inputs.append((Path(item['path']).stem, load(root / item['path'])))
inputs.append(('math', load(root / '.local/verification/d2/pipeline-input.wav')))
rows = []
with redirect_stdout(sys.stderr):
    for index, (name, audio) in enumerate(inputs):
        modes = ['baseline', 'single', 'compiled-single'] if index % 2 == 0 else ['compiled-single', 'single', 'baseline']
        for mode in modes:
            model.encoder = compiled if mode == 'compiled-single' else original
            started = time.monotonic()
            try:
                with request_encoder(model, key=_mel_key):
                    if mode == 'baseline':
                        result = whisper.transcribe(audio, path_or_hf_repo=model_id, word_timestamps=True, verbose=None)
                    else:
                        mel = whisper.log_mel_spectrogram(audio, n_mels=model.dims.n_mels, padding=audio_lib.N_SAMPLES)
                        frames = mel.shape[-2] - audio_lib.N_FRAMES
                        segment = audio_lib.pad_or_trim(mel[:frames], audio_lib.N_FRAMES, axis=-2).astype(mx.float16)
                        _, probabilities = model.detect_language(segment)
                        language = max(probabilities, key=probabilities.get)
                        result = whisper.transcribe(audio, path_or_hf_repo=model_id, word_timestamps=True, verbose=None, language=language)
                rows.append({'input': name, 'mode': mode, 'seconds': time.monotonic() - started, 'text': result['text'], 'language': result['language'], 'words': [w for s in result['segments'] for w in s.get('words', [])]})
            finally:
                model.encoder = original
        report = {'passed': True, 'kind': 'private same-model development probe, auto language from exact decode mel; no production change', 'asr_model': model_id, 'tts_model': os.environ['ME3_TTS_MODEL'], 'voice': os.environ['ME3_TTS_VOICE'], 'rows': rows}
        (root / '.local/verification/targets/asr/single-native-progress.json').write_text(json.dumps(report, indent=2) + '\n')
report['passed'] = all(len({(r['text'], r['language']) for r in rows if r['input'] == name}) == 1 for name, _ in inputs)
(root / '.local/verification/targets/asr/single-native.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
