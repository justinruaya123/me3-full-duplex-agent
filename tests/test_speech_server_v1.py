"""Authenticated speech HTTP contracts; fixture models are not MLX evidence."""

import unittest


class SpeechServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_warmup_prevents_listening_and_closes_models(self):
        from aiohttp.test_utils import TestServer

        from me3.speech_server import SpeechServerConfig, create_app

        class UnavailableModels:
            closed = False

            async def warmup(self):
                raise RuntimeError("native model unavailable")

            async def close(self):
                self.closed = True

        models = UnavailableModels()
        server = TestServer(create_app(
            SpeechServerConfig("asr", "tts", "voice", "token"), models
        ))
        try:
            with self.assertRaisesRegex(RuntimeError, "native model"):
                await server.start_server()
            self.assertTrue(models.closed)
        finally:
            await server.close()

    async def test_empty_or_invalid_first_pcm_cannot_return_success(self):
        from aiohttp.test_utils import TestClient, TestServer

        from me3.speech_server import SpeechServerConfig, create_app

        for chunks in ([], [b""], [b"\x01"]):
            with self.subTest(chunks=chunks):
                class Models:
                    async def synthesize(self, text):
                        for pcm in chunks:
                            yield pcm

                async with TestClient(TestServer(create_app(
                    SpeechServerConfig("asr", "tts", "voice", "token"),
                    Models(),
                ))) as client:
                    response = await client.post(
                        "/v1/audio/speech",
                        json={
                            "model": "tts", "voice": "voice",
                            "input": "hello", "response_format": "pcm",
                        },
                        headers={"Authorization": "Bearer token"},
                    )
                    self.assertEqual(response.status, 502)
                    self.assertIn("audio", await response.text())

    async def test_auth_exact_models_and_raw_pcm_contract(self):
        from aiohttp.test_utils import TestClient, TestServer

        from me3.speech_server import SpeechServerConfig, create_app

        class Models:
            async def transcribe(self, pcm):
                return {"text": "fixture transcript"}

            async def synthesize(self, text):
                yield b"\x01\x00" * 480

        config = SpeechServerConfig(
            "exact-asr", "exact-tts", "voice", "test-token"
        )
        async with TestClient(
            TestServer(create_app(config, Models()))
        ) as client:
            for url in ("/", "/v1", "/v1/", "/v1/models"):
                page = await client.get(url, headers={"Accept": "text/html"})
                self.assertEqual(page.status, 200)
                self.assertIn("ME3 speech server is online", await page.text())
            response = await client.get("/v1/models")
            self.assertEqual(response.status, 401)
            response = await client.get(
                "/v1/models", headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(response.status, 200)
            response = await client.post(
                "/v1/audio/speech",
                json={
                    "model": "substitute",
                    "voice": "voice",
                    "input": "hello",
                    "response_format": "pcm",
                },
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(response.status, 400)
            response = await client.post(
                "/v1/audio/speech",
                json={
                    "model": "exact-tts",
                    "voice": "voice",
                    "input": "hello",
                    "response_format": "pcm",
                },
                headers={"Authorization": "Bearer test-token"},
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(len(await response.read()), 960)

    async def test_partial_upload_reserves_single_role_capacity(self):
        import asyncio
        import json

        from aiohttp.test_utils import TestClient, TestServer

        from me3.speech_server import SpeechServerConfig, create_app

        begun, release = asyncio.Event(), asyncio.Event()

        class Models:
            async def synthesize(self, text):
                yield bytes(960)

        config = SpeechServerConfig("asr", "tts", "voice", "token")
        payload = json.dumps(
            {
                "model": "tts",
                "voice": "voice",
                "input": "hello",
                "response_format": "pcm",
            }
        ).encode()

        async def upload():
            yield payload[:1]
            begun.set()
            await release.wait()
            yield payload[1:]

        async with TestClient(
            TestServer(create_app(config, Models()))
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/audio/speech",
                    data=upload(),
                    headers={
                        "Authorization": "Bearer token",
                        "Content-Type": "application/json",
                    },
                )
            )
            try:
                await begun.wait()
                await asyncio.sleep(0.05)
                second = await client.post(
                    "/v1/audio/speech",
                    data=payload,
                    headers={
                        "Authorization": "Bearer token",
                        "Content-Type": "application/json",
                    },
                )
                self.assertEqual(second.status, 503)
            finally:
                release.set()
                response = await first
                await response.read()

    async def test_cancelled_native_call_stays_busy_until_thread_finishes(
        self,
    ):
        import asyncio
        import threading

        from aiohttp.test_utils import TestClient, TestServer

        from me3.speech_server import (
            MLXSpeechModels,
            SpeechServerConfig,
            create_app,
        )

        class CapacityModels(MLXSpeechModels):
            async def warmup(self):
                # This test exercises a real native thread, not GPU inference.
                pass

        config = SpeechServerConfig("asr", "tts", "voice", "token")
        models = CapacityModels(config)
        started, release = threading.Event(), threading.Event()

        def blocked():
            started.set()
            release.wait(5)

        task = None
        try:
            task = asyncio.create_task(models._native("tts", blocked))
            await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            async with TestClient(
                TestServer(create_app(config, models))
            ) as client:
                response = await client.post(
                    "/v1/audio/speech",
                    json={
                        "model": "tts",
                        "voice": "voice",
                        "input": "hello",
                        "response_format": "pcm",
                    },
                    headers={"Authorization": "Bearer token"},
                )
                self.assertEqual(response.status, 503)
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            await models.close()


class SpeechCheckTests(unittest.TestCase):
    def test_readiness_rejects_silence_truncation_and_wrong_transcript(self):
        from me3.speech_server import CHECK_TEXT, validate_sample

        for pcm, text in (
            (b"", CHECK_TEXT),
            (bytes(48000), CHECK_TEXT),
            (b"\x01", CHECK_TEXT),
            (b"\x01\x00" * (16 * 24000 + 1), CHECK_TEXT),
            (b"\x01\x00" * 24000, "unrelated recognized speech"),
        ):
            with self.subTest(bytes=len(pcm), transcript=text):
                with self.assertRaises(ValueError):
                    validate_sample(pcm, text)

    def test_readiness_accepts_recognized_phrase_with_asr_punctuation(self):
        from me3.speech_server import validate_sample

        validate_sample(
            b"\x01\x00" * 24000,
            " Hello, the voice system is ready. ",
        )

class ListenAddressTests(unittest.TestCase):
    def test_supervisor_preserves_both_explicit_interfaces(self):
        from unittest.mock import patch
        from me3.speech_server import main
        import os

        env = {"ME3_ASR_MODEL": "mlx-community/whisper-large-v3-turbo",
               "ME3_TTS_MODEL": "mlx-community/Kokoro-82M-bf16",
               "ME3_TTS_VOICE": "af_heart", "ME3_SPEECH_SERVER_TOKEN": "test-local"}
        args = ["speech", "--host", "127.0.0.1", "--host", "192.0.2.20"]
        with patch.dict(os.environ, env), patch("sys.argv", args), patch(
            "me3.speech_check.run_guarded_service", return_value=0
        ) as run, self.assertRaises(SystemExit):
            main()
        cmd = run.call_args.args[0]
        self.assertEqual([cmd[i+1] for i, arg in enumerate(cmd) if arg == "--host"], args[2::2])
