"""Exclusive native experiment: same weights, fused encoder attention only."""
import importlib,json,os,time,wave
from contextlib import contextmanager
from pathlib import Path
import mlx.core as mx
import numpy as np
from scipy.signal import resample_poly
from me3.whisper_inference import request_encoder,_mel_key
ROOT=Path(__file__).resolve().parents[4]
whisper=importlib.import_module('mlx_whisper.transcribe')
model_id=os.environ['ME3_ASR_MODEL'];model=whisper.ModelHolder.get_model(model_id,mx.float16)
with wave.open(str(ROOT/'docs/evidence/2026-11-07/d2/voice-sample.wav')) as f:
 x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.float32)/32768
x=resample_poly(x,2,3)

@contextmanager
def fused_encoder(enabled):
 saved=[]
 try:
  if enabled:
   for block in model.encoder.blocks:
    attn=block.attn;old=attn.qkv_attention;heads=attn.n_head
    def fast(q,k,v,mask=None,heads=heads):
     batch,length,width=q.shape
     q=q.reshape(batch,length,heads,-1).transpose(0,2,1,3)
     k=k.reshape(k.shape[0],k.shape[1],heads,-1).transpose(0,2,1,3)
     v=v.reshape(v.shape[0],v.shape[1],heads,-1).transpose(0,2,1,3)
     out=mx.fast.scaled_dot_product_attention(q,k,v,scale=(width//heads)**-.5,mask=mask)
     return out.transpose(0,2,1,3).reshape(batch,length,width),None
    saved.append((attn,old));attn.qkv_attention=fast
  yield
 finally:
  for attn,old in saved:attn.qkv_attention=old

trials=[]
for mode,fused,lang in [('warm',False,None),('cached_auto',False,None),('fused_auto',True,None),('fused_auto',True,None),('fused_english',True,'en'),('fused_english',True,'en')]:
 started=time.monotonic()
 with fused_encoder(fused):
  with request_encoder(model,key=_mel_key):
   result=whisper.transcribe(x,path_or_hf_repo=model_id,word_timestamps=True,verbose=None,language=lang)
 trials.append({'mode':mode,'seconds':time.monotonic()-started,'text':result['text'],'language':result['language'],'words':[w for s in result['segments'] for w in s.get('words',[])]})
print(json.dumps({'passed':all('voice system is ready' in t['text'].lower() and t['words'] for t in trials),'asr_model':model_id,'tts_model':os.environ['ME3_TTS_MODEL'],'voice':os.environ['ME3_TTS_VOICE'],'kind':'same weights native development experiment; full context and word alignment','trials':trials}))
