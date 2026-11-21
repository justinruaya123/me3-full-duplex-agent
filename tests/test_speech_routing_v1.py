import unittest
from unittest.mock import AsyncMock, patch

import httpx

from me3.audio_pipeline import ConfiguredSpeech
from me3.duplex_voice import settings


ASR = {
    "ME3_ASR_API_KEY": "fixture",
    "ME3_ASR_MODEL": "whisper",
    "ME3_ASR_BASE_URL": "http://localhost/v1",
}


class SpeechRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_synthesis_uses_client_without_tts_http(self):
        config = settings(ASR)
        self.assertEqual(config["tts_backend"], "local")
        self.assertNotIn("tts_base_url", config)

        async def pcm(_):
            yield bytes(960)

        with patch("me3.local_tts.LocalKokoro") as engine:
            engine.return_value.synthesize.side_effect = pcm
            engine.return_value.close = AsyncMock()
            speech = ConfiguredSpeech(config)
            with patch.object(httpx.AsyncClient, "send", side_effect=AssertionError):
                self.assertEqual(
                    [c async for c in speech.synthesize("Hi")], [bytes(960)]
                )
            await speech.close()
            engine.return_value.close.assert_awaited_once()

    async def test_server_synthesis_needs_no_local_assets(self):
        config = settings(
            dict(
                ASR,
                ME3_TTS_BACKEND="server",
                ME3_TTS_MODEL="kokoro",
                ME3_TTS_VOICE="af_heart",
                ME3_TTS_API_KEY="fixture",
                ME3_TTS_BASE_URL="http://localhost:8002/v1",
            )
        )
        self.assertEqual(config["tts_backend"], "server")
        with patch.object(
            httpx.AsyncClient,
            "send",
            autospec=True,
            return_value=httpx.Response(
                200,
                content=bytes(960),
                request=httpx.Request("POST", "http://localhost"),
            ),
        ) as send:
            speech = ConfiguredSpeech(config)
            try:
                self.assertEqual(
                    [c async for c in speech.synthesize("Hi")], [bytes(960)]
                )
                self.assertEqual(
                    send.call_args.kwargs["request"].url.path, "/v1/audio/speech"
                )
            finally:
                await speech.close()

    async def test_close_while_native_inference_is_stalled(self):
        import asyncio
        import sys
        from pathlib import Path
        from me3.local_tts import LocalKokoro

        create = asyncio.create_subprocess_exec
        stalled = asyncio.Event()

        async def fake_native(*args, **kwargs):
            script = (
                "import sys,time; print('ready', flush=True); "
                "sys.stdin.buffer.readline(); time.sleep(90)"
            )
            return await create(sys.executable, "-c", script, **kwargs)

        engine = LocalKokoro(Path("."))
        with patch("asyncio.create_subprocess_exec", side_effect=fake_native):
            await engine.start()
            process = engine.process

            async def request():
                stalled.set()
                return [pcm async for pcm in engine.synthesize("hello")]

            task = asyncio.create_task(request())
            await stalled.wait()
            try:
                await asyncio.wait_for(engine.close(), 2)
            finally:
                result = await asyncio.gather(task, return_exceptions=True)
            self.assertIsInstance(result[0], Exception)
            self.assertIsNotNone(process.returncode)

    def test_verifier_stays_on_client(self):
        from me3.ownership import HTTPVoiceVerifier

        with self.assertRaisesRegex(ValueError, "client"):
            HTTPVoiceVerifier("http://speech-server:8002", "token")
        HTTPVoiceVerifier("http://127.0.0.1:8070", "token")

    def test_benchmark_records_model_actually_selected(self):
        import os
        from integrations.fdbench_entry import describe
        from me3.local_tts import BUNDLE

        for backend, expected in (("local", BUNDLE), ("server", "historical-mlx")):
            with (
                self.subTest(backend=backend),
                patch.dict(
                    os.environ,
                    {
                        "ME3_TTS_BACKEND": backend,
                        "ME3_TTS_MODEL": "historical-mlx",
                    },
                    clear=True,
                ),
            ):
                self.assertEqual(describe()["TTS"], expected)
                self.assertEqual(describe()["TTS_backend"], backend)

    def test_launcher_explicit_backend_overrides_saved_default(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "scripts/me3.sh"
            script.parent.mkdir()
            script.write_bytes(Path("scripts/me3.sh").read_bytes())
            (root / ".env").write_text("ME3_TTS_BACKEND=local\n")
            python = root / ".venv313/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "%s" "$ME3_TTS_BACKEND"\n')
            python.chmod(0o755)
            selected = subprocess.check_output(
                ["bash", str(script), "tts-probe"],
                env={"PATH": os.environ["PATH"], "ME3_TTS_BACKEND": "server"},
                text=True,
            )
            self.assertEqual(selected, "server")

    def test_loopback_server_routes_require_authentication(self):
        with self.assertRaisesRegex(ValueError, "authentication"):
            settings(dict(ASR, ME3_ASR_API_KEY=""))
        with self.assertRaisesRegex(ValueError, "authentication"):
            settings(
                dict(
                    ASR,
                    ME3_ASR_API_KEY="test",
                    ME3_TTS_BACKEND="server",
                    ME3_TTS_BASE_URL="http://127.0.0.1/v1",
                    ME3_TTS_MODEL="test",
                    ME3_TTS_VOICE="test",
                )
            )
