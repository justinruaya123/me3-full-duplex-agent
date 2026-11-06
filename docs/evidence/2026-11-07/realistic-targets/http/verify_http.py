"""Real local HTTP speech checks; synthetic inputs only."""
import asyncio
import io
import json
import os
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import soxr

from me3.speech_server import CHECK_TEXT, validate_sample

ROOT = Path(__file__).resolve().parent
BASE = os.environ['ME3_ASR_BASE_URL'].rstrip('/')
HEADERS = {'Authorization': 'Bearer ' + os.environ['ME3_SPEECH_SERVER_TOKEN']}


def wav(pcm, rate):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(pcm)
    return output.getvalue()


def asr_wav(pcm):
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32)
    audio = soxr.resample(samples, 24000, 16000)
    return wav(np.clip(audio, -32768, 32767).astype('<i2').tobytes(), 16000)


async def main():
    report = {'kind': 'real authenticated local ASR/TTS HTTP; synthetic speech, no acoustic recording', 'checks': {}, 'trials': []}
    async with httpx.AsyncClient(timeout=45) as client:
        async def synthesize(text):
            started = time.monotonic()
            chunks, first = [], None
            async with client.stream('POST', BASE + '/audio/speech', headers=HEADERS, json={
                'model': os.environ['ME3_TTS_MODEL'], 'voice': os.environ['ME3_TTS_VOICE'],
                'input': text, 'response_format': 'pcm',
            }) as response:
                response.raise_for_status()
                async for part in response.aiter_bytes():
                    if first is None:
                        first = time.monotonic() - started
                    chunks.append(part)
            pcm = b''.join(chunks)
            return pcm, {'first_pcm_seconds': first, 'total_seconds': time.monotonic() - started, 'audio_seconds': len(pcm)/48000}

        async def transcribe(audio):
            started = time.monotonic()
            response = await client.post(BASE + '/audio/transcriptions', headers=HEADERS,
                data={'model': os.environ['ME3_ASR_MODEL']},
                files={'file': ('synthetic.wav', audio, 'audio/wav')})
            response.raise_for_status()
            return response.json(), time.monotonic() - started

        for _ in range(180):
            try:
                unauthorized = await client.get(BASE + '/models')
                break
            except httpx.ConnectError:
                await asyncio.sleep(.25)
        else:
            raise TimeoutError('Speech server did not become ready')
        report['checks']['unauthenticated_rejected'] = unauthorized.status_code == 401
        catalog = await client.get(BASE + '/models', headers=HEADERS)
        catalog.raise_for_status()
        ids = {item['id'] for item in catalog.json()['data']}
        report['checks']['exact_catalog'] = ids == {os.environ['ME3_ASR_MODEL'], os.environ['ME3_TTS_MODEL']}
        invalid = await client.post(BASE + '/audio/speech', headers=HEADERS, json={
            'model': 'not-the-selected-model', 'voice': os.environ['ME3_TTS_VOICE'],
            'input': 'hello', 'response_format': 'pcm'})
        report['checks']['model_substitution_rejected'] = invalid.status_code == 400
        for index, text in enumerate((CHECK_TEXT, 'What is seventeen plus twenty five?')):
            pcm, timing = await synthesize(text)
            decoded, asr_seconds = await transcribe(asr_wav(pcm))
            if index == 0:
                validate_sample(pcm, decoded['text'])
                report['checks']['exact_phrase_roundtrip'] = True
            else:
                question = decoded['text'].casefold()
                report['checks']['question_transcribed'] = ('seventeen' in question or '17' in question) and ('twenty' in question or '25' in question)
            report['trials'].append({'text': text, 'transcript': decoded['text'], 'tts': timing, 'asr_seconds': asr_seconds, 'word_timestamps': sum(len(seg.get('words', [])) for seg in decoded.get('segments', []))})
            name = 'http-sample.wav' if index == 0 else 'pipeline-input.wav'
            (ROOT / name).write_bytes(wav(pcm, 24000))
        audio = asr_wav(pcm)
        (decoded, asr_seconds), (other_pcm, timing) = await asyncio.gather(transcribe(audio), synthesize(CHECK_TEXT))
        validate_sample(other_pcm, CHECK_TEXT)
        report['checks']['concurrent_asr_tts_completed'] = bool(decoded['text'].strip())
        report['concurrent'] = {'asr_seconds': asr_seconds, 'tts': timing, 'transcript': decoded['text']}
        report['passed'] = all(report['checks'].values())
    output = json.dumps(report, indent=2) + '\n'
    (ROOT / 'http-roundtrip.json').write_text(output)
    print(output)

asyncio.run(main())
