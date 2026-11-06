"""Private same-model language uncertainty probe; no benchmark input."""
import importlib
import json
import os
import wave
from pathlib import Path
import mlx.core as mx
import numpy as np
from scipy.signal import resample_poly
from me3.whisper_inference import _mel_key, request_encoder
root=Path(__file__).resolve().parents[4]
whisper=importlib.import_module('mlx_whisper.transcribe')
audio_lib=importlib.import_module('mlx_whisper.audio')
model_id=os.environ['ME3_ASR_MODEL'];model=whisper.ModelHolder.get_model(model_id,mx.float16)
rows=[]
paths=[root/'docs/evidence/2026-11-07/d2/voice-sample.wav']+sorted((root/'.local/verification/targets/vad/development-speech').glob('*.wav'))
for path in paths:
 with wave.open(str(path)) as stream:
  audio=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
  audio=resample_poly(audio,16000,stream.getframerate()).astype(np.float32)
 mel=whisper.log_mel_spectrogram(audio,n_mels=model.dims.n_mels,padding=audio_lib.N_SAMPLES)
 frames=mel.shape[-2]-audio_lib.N_FRAMES
 for mode,segment in [('standard',audio_lib.pad_or_trim(mel,audio_lib.N_FRAMES,axis=-2)),('decode',audio_lib.pad_or_trim(mel[:frames],audio_lib.N_FRAMES,axis=-2))]:
  _,probs=model.detect_language(segment.astype(mx.float16))
  rows.append({'input':path.name,'mode':mode,'probabilities':dict(sorted(probs.items(),key=lambda p:p[1],reverse=True)[:5])})
report={'passed':True,'asr_model':model_id,'rows':rows}
(root/'.local/verification/targets/asr/language-native.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
