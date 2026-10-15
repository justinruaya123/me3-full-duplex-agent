"""Model contracts and local process lifecycle, without real inference."""

import asyncio
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from me3.backends import ProcessBackend
from me3.speech import EnergyVAD, HTTPSpeech


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 320)
    return output.getvalue()


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_child_protocol_and_no_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "child.py"
            runner.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "request=json.loads(Path(sys.argv[1]).read_text())\n"
                "Path(sys.argv[2]).write_text("
                "json.dumps({'text':request['prompt']}))\n"
            )
            backend = ProcessBackend([sys.executable, str(runner)])
            result = await backend.run("literal ; $(no-shell)", root)
            self.assertEqual(result, "literal ; $(no-shell)")

    async def test_child_failure_is_not_mock_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = ProcessBackend(
                [sys.executable, "-c", "raise SystemExit(3)"],
            )
            with self.assertRaises(RuntimeError):
                await backend.run("hello", Path(directory))

    async def test_timeout_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = ProcessBackend(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=0.05
            )
            with self.assertRaises(TimeoutError):
                await backend.run("hello", Path(directory))
            self.assertEqual(backend.active_pids, set())

    async def test_cancellation_reaps_child(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = ProcessBackend(
                [sys.executable, "-c", "import time; time.sleep(60)"]
            )
            task = asyncio.create_task(backend.run("hello", Path(directory)))
            while not backend.active_pids:
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(backend.active_pids, set())


class VADTests(unittest.TestCase):
    def test_preroll_start_end_and_duration_limit(self):
        vad = EnergyVAD(
            threshold=100,
            start_frames=2,
            silence_frames=3,
            max_frames=20,
        )
        silence = b"\x00\x00" * 320
        speech = b"\xe8\x03" * 320
        self.assertEqual(vad.feed(silence), (False, None))
        vad.feed(speech)
        started, audio = vad.feed(speech)
        self.assertTrue(started)
        self.assertIsNone(audio)
        for _ in range(2):
            self.assertIsNone(vad.feed(silence)[1])
        clip = vad.feed(silence)[1]
        self.assertIsNotNone(clip)
        with wave.open(io.BytesIO(clip)) as stream:
            self.assertEqual(stream.getframerate(), 16000)
            self.assertGreaterEqual(stream.getnframes(), 6 * 320)
        self.assertFalse(vad.active)

    def test_overlong_speech_is_dropped_not_executed(self):
        vad = EnergyVAD(threshold=100, start_frames=1, max_frames=4)
        speech = b"\xe8\x03" * 320
        for _ in range(4):
            self.assertIsNone(vad.feed(speech)[1])
        self.assertTrue(vad.overflowed)
        self.assertFalse(vad.active)

    def test_wrong_frame_size_rejected(self):
        with self.assertRaises(ValueError):
            EnergyVAD().feed(b"bad")


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_contracts_and_pcm_stream(self):
        import httpx

        requests = []

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("transcriptions"):
                return httpx.Response(200, json={"text": "hello"})
            return httpx.Response(200, content=b"\x01\x00" * 3000)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond),
        ) as client:
            speech = HTTPSpeech(
                (
                    "http://inference/audio/transcriptions"
                ), "http://inference/audio/speech",
                "asr-model", "tts-model", client=client,
            )
            self.assertEqual(await speech.transcribe(wav_bytes()), "hello")
            chunks = [chunk async for chunk in speech.synthesize("answer")]
            self.assertEqual(sum(map(len, chunks)), 6000)
            payload = json.loads(requests[-1].content)
            self.assertEqual(payload["response_format"], "pcm")

    async def test_bad_audio_and_provider_errors_fail_closed(self):
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        ) as client:
            speech = HTTPSpeech(
                "http://inference/asr", "http://inference/tts",
                "asr", "tts", client=client
            )
            with self.assertRaises(ValueError):
                await speech.transcribe(b"not a wav")
            with self.assertRaises(httpx.HTTPStatusError):
                await speech.transcribe(wav_bytes())


if __name__ == "__main__":
    unittest.main()
