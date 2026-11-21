import asyncio, hashlib, json, time
from pathlib import Path
from me3.audio_pipeline import ConfiguredSpeech
from me3.duplex_voice import settings

async def main():
    config = settings()
    speech = ConfiguredSpeech(config)
    rows = []
    try:
        for _ in range(2):
            started = time.monotonic()
            pcm = b''.join([p async for p in speech.synthesize('Mm-hm.')])
            rows.append({'seconds': time.monotonic()-started,
                         'bytes': len(pcm), 'sha256': hashlib.sha256(pcm).hexdigest()})
        result = {'scope': 'real authenticated Kokoro HTTP, exact-PCM cache reuse; no microphone/acoustics',
                  'model': config['tts_model'], 'voice': config['tts_voice'],
                  'runs': rows, 'passed': rows[0]['bytes'] > 0 and rows[0]['sha256']==rows[1]['sha256']}
        Path('.local/verification/conversation-return/real-cue-smoke.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result))
        if not result['passed']:
            raise SystemExit(1)
    finally:
        await speech.close()
asyncio.run(main())
