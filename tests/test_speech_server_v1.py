"""Authenticated speech HTTP contracts; fixture models are not MLX evidence."""

import unittest


class SpeechServerTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_cancelled_native_inference_remains_busy_until_thread_finishes(
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

        config = SpeechServerConfig("asr", "tts", "voice", "token")
        models = MLXSpeechModels(config)
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
