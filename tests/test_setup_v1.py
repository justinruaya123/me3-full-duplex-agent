"""Explicit role configuration, without inference or credentials."""

import os
import sys
import unittest
from unittest.mock import patch

from me3.harnesses import PiBackend, configured_backend


class SetupTests(unittest.TestCase):
    def test_pi_is_default_and_worker_model_is_explicit(self):
        with patch.dict(
            os.environ,
            {
                "ME3_PI_BIN": sys.executable,
                "ME3_WORKER_MODEL": "operator/exact-model",
            },
            clear=True,
        ):
            backend = configured_backend()
        self.assertIsInstance(backend, PiBackend)
        self.assertIn("operator/exact-model", backend.command)

    def test_missing_worker_model_never_uses_foreground_model(self):
        with patch.dict(
            os.environ,
            {
                "ME3_PI_BIN": sys.executable,
                "ME3_FOREGROUND_MODEL": "conversation-only",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "WORKER_MODEL"):
                configured_backend()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ending_voice_session_keeps_real_supervisor_job_alive(self):
        import asyncio
        import tempfile
        from pathlib import Path

        from me3.runtime import AgentRuntime

        started, release = asyncio.Event(), asyncio.Event()

        class Worker:
            async def run(self, prompt, workspace, *, foreground=False):
                started.set()
                await release.wait()
                return "verified worker result"

        async def speak(text):
            return True

        async def stop():
            pass

        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(Path(directory), Worker(), Worker())
            try:
                session = runtime.open_session(speak, stop)
                job = runtime.supervisor.submit("independent task")
                await started.wait()
                await runtime.end_session(session)
                self.assertEqual(
                    runtime.supervisor.get(job["id"])["status"], "running"
                )
                release.set()
                await runtime.supervisor.wait(job["id"])
                self.assertEqual(
                    runtime.supervisor.result(job["id"]),
                    "verified worker result",
                )
            finally:
                release.set()
                await runtime.close()


class ConfigurationTests(unittest.TestCase):
    def test_foreground_never_inherits_worker_credentials_or_model(self):
        from me3.configuration import ForegroundConfig

        with self.assertRaisesRegex(ValueError, "FOREGROUND"):
            ForegroundConfig.from_env({"ME3_WORKER_MODEL": "worker"})

    def test_foreground_rejects_credentials_in_url_and_unknown_profile(self):
        from me3.configuration import ForegroundConfig

        env = {
            "ME3_FOREGROUND_PROFILE": "qwen",
            "ME3_FOREGROUND_MODEL": "exact-id",
            "ME3_FOREGROUND_BASE_URL": "https://secret@example.com/v1",
        }
        with self.assertRaises(ValueError):
            ForegroundConfig.from_env(env)
        env["ME3_FOREGROUND_BASE_URL"] = "http://localhost:8001/v1"
        env["ME3_FOREGROUND_PROFILE"] = "invented"
        with self.assertRaises(ValueError):
            ForegroundConfig.from_env(env)


class ForegroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_enforces_model_and_disables_reasoning(self):
        import json

        import httpx

        from me3.configuration import ForegroundConfig
        from me3.foreground import ForegroundBackend

        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            data = {
                "model": "exact-id",
                "choices": [
                    {"delta": {"content": "Hello."}, "finish_reason": None}
                ],
            }
            return httpx.Response(
                200, text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n"
            )

        config = ForegroundConfig(
            "qwen", "http://localhost/v1", "exact-id", ""
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as client:
            backend = ForegroundBackend(config, client=client)
            answer = "".join([part async for part in backend.stream("hello")])
        self.assertEqual(answer, "Hello.")
        self.assertFalse(
            requests[0]["chat_template_kwargs"]["enable_thinking"]
        )
        self.assertNotIn("tools", requests[0])

    async def test_silent_model_substitution_is_rejected(self):
        import json

        import httpx

        from me3.configuration import ForegroundConfig
        from me3.foreground import ForegroundBackend

        data = {
            "model": "substituted",
            "choices": [{"delta": {"content": "wrong"}}],
        }
        config = ForegroundConfig(
            "qwen", "http://localhost/v1", "exact-id", ""
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, text="data: " + json.dumps(data) + "\n\n"
                )
            )
        ) as client:
            with self.assertRaisesRegex(ValueError, "model"):
                async for _ in ForegroundBackend(config, client=client).stream(
                    "hello"
                ):
                    pass


class DoctorTests(unittest.TestCase):
    def test_report_identifies_missing_roles_without_exposing_credentials(
        self,
    ):
        import json

        from me3.doctor import configuration_report

        report = configuration_report(
            {
                "ME3_FOREGROUND_API_KEY": "never-print-this",
                "ME3_TTS_API_KEY": "also-secret",
            }
        )
        self.assertFalse(report["ready"])
        self.assertIn("foreground", report["blockers"])
        self.assertNotIn("never-print-this", json.dumps(report))
        self.assertNotIn("also-secret", json.dumps(report))

    def test_voice_lan_endpoints_require_authentication(self):
        from me3.duplex_voice import settings

        env = {
            "ME3_ASR_BASE_URL": "http://192.168.1.2:8000/v1",
            "ME3_ASR_MODEL": "exact-asr",
            "ME3_TTS_BASE_URL": "http://192.168.1.2:8880/v1",
            "ME3_TTS_MODEL": "exact-tts",
            "ME3_TTS_VOICE": "exact-voice",
        }
        with self.assertRaisesRegex(ValueError, "authentication"):
            settings(env)


class ProbeFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_requested_probe_cannot_report_ready(self):
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        from me3.doctor import _main

        with (
            patch(
                "me3.doctor.configuration_report",
                return_value={"ready": True, "blockers": []},
            ),
            patch(
                "me3.doctor.provider_probe",
                new=AsyncMock(side_effect=ConnectionError("offline")),
            ),
        ):
            report = await _main(
                Namespace(pi_rpc=False, inference=True, audio=False)
            )
        self.assertFalse(report["ready"])
        self.assertFalse(report["provider_inference"]["passed"])
