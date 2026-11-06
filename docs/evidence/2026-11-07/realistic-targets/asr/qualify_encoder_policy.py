"""Actual-native RED/GREEN: same-model automatic language, exact words, calls."""
import importlib
import json
import os
import sys
import time
import wave
from contextlib import redirect_stdout
from pathlib import Path

import mlx.core as mx
import numpy as np
from scipy.signal import resample_poly

from me3.whisper_inference import _mel_key, request_encoder, transcribe_whisper

root=Path(__file__).resolve().parents[4]
whisper=importlib.import_module('mlx_whisper.transcribe')
model_id=os.environ['ME3_ASR_MODEL'];model=whisper.ModelHolder.get_model(model_id,mx.float16)
original=model.encoder

def load(path):
 with wave.open(str(path)) as stream:
  samples=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
  return resample_poly(samples,16000,stream.getframerate()).astype(np.float32)

cases=[('ready',root/'docs/evidence/2026-11-07/d2/voice-sample.wav',1),('math',root/'.local/verification/d2/pipeline-input.wav',1),('ambiguous',root/'.local/verification/targets/vad/development-speech/04.wav',2)]
cases += [(f'dev-{i:02}', root / f'.local/verification/targets/vad/development-speech/{i:02}.wav', 1) for i in (1, 2, 3, 5, 6, 7, 8)]
cases = [(f'{name}-r{repeat}', path, expected) for repeat in (1, 2) for name, path, expected in cases]
rows=[]
with redirect_stdout(sys.stderr):
 for name,path,expected in cases:
  audio=load(path)
  for variant in (('reference','project') if len(rows) % 4 == 0 else ('project','reference')):
   calls=[]
   def encode(mel):
    calls.append({'shape':list(mel.shape)})
    return original(mel)
   model.encoder=encode
   started=time.monotonic()
   try:
    if variant=='reference':
     with request_encoder(model,key=_mel_key):
      result=whisper.transcribe(audio,path_or_hf_repo=model_id,word_timestamps=True,verbose=None)
    else:
     result=transcribe_whisper(audio,model_id)
   finally:
    model.encoder=original
   rows.append({'input':name,'variant':variant,'expected_project_calls':expected,'encoder_calls':len(calls),'seconds':time.monotonic()-started,'text':result['text'],'language':result['language'],'words':[w for segment in result['segments'] for w in segment.get('words',[])]})
report={'passed':all(row['encoder_calls']==row['expected_project_calls'] for row in rows if row['variant']=='project') and all(rows[i]['text']==rows[i+1]['text'] and rows[i]['language']==rows[i+1]['language'] and rows[i]['words']==rows[i+1]['words'] for i in range(0,len(rows),2)), 'kind':'actual native same-weight RED/GREEN with reference language path; generated development speech','asr_model':model_id,'rows':rows}
label=sys.argv[1]
(root/f'.local/verification/targets/asr/encoder-policy-{label}.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
