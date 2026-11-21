"""Independent operator-selected roles exercised through the runtime factories."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from me3.configuration import FLASH_LITE, GPT_OSS, OPENROUTER_BASE_URL
from me3.doctor import configuration_report
from me3.foreground import configured_foreground
from me3.harnesses import configured_backend


QWEN = {
    "ME3_FOREGROUND_PROFILE": "qwen",
    "ME3_FOREGROUND_BASE_URL": "http://localhost:8000/v1",
    "ME3_FOREGROUND_MODEL": "qwen/exact",
    "ME3_FOREGROUND_API_KEY": "foreground-only",
    "ME3_HARNESS": "direct",
    "ME3_WORKER_PROVIDER": "qwen",
    "ME3_WORKER_BASE_URL": "http://localhost:8001/v1",
    "ME3_WORKER_MODEL": "qwen/exact/worker",
    "ME3_WORKER_API_KEY": "worker-only",
    "ME3_PI_BIN": "/unavailable/pi",
}
ROUTED_FG = {
    "ME3_FOREGROUND_PROFILE": "openrouter",
    "ME3_FOREGROUND_BASE_URL": OPENROUTER_BASE_URL,
    "ME3_FOREGROUND_MODEL": FLASH_LITE,
    "ME3_FOREGROUND_PROVIDER": "google-ai-studio",
    "OPENROUTER_API_KEY": "gateway-only",
}
ROUTED_WORKER = {
    "ME3_WORKER_PROVIDER": "openrouter",
    "ME3_WORKER_MODEL": GPT_OSS,
    "OPENROUTER_API_KEY": "gateway-only",
}


def completion(model, content="Done", **fields):
    return {
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        **fields,
    }


class RoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_compatible_can_send_a_configured_stop_token(self):
        env = QWEN | {"ME3_FOREGROUND_PROFILE": "compatible",
                      "ME3_FOREGROUND_STOP": "<|im_end|>"}
        backend = configured_foreground(env=env)

        def answer(request):
            data = json.loads(request.content)
            self.assertEqual(data["stop"], ["<|im_end|>"])
            chunks = [{"model": data["model"], "choices": [{"delta": {"content": text}}]}
                      for text in ("Hi<|im_", "end|>", "spurious trailer")]
            events = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            return httpx.Response(200, text=events + "data: [DONE]\n\n")

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            backend.client = client
            self.assertEqual(await backend.run("Hi", Path(".")), "Hi")

    async def test_operator_model_and_route_checked_for_both_openrouter_roles(self):
        env = QWEN | ROUTED_FG | ROUTED_WORKER | {
            "ME3_FOREGROUND_MODEL": "operator/foreground", "ME3_FOREGROUND_PROVIDER": "vendor-a",
            "ME3_FOREGROUND_PROVIDER_NAME": "Vendor A", "ME3_WORKER_MODEL": "operator/worker",
            "ME3_WORKER_BASE_URL": "", "ME3_WORKER_ROUTING_PROVIDER": "vendor-b/fp8",
            "ME3_WORKER_ROUTING_PROVIDER_NAME": "Vendor B",
        }
        foreground = configured_foreground(env=env)
        worker = configured_backend(env)
        pi = configured_backend(env | {"ME3_HARNESS": "pi", "ME3_PI_BIN": sys.executable})
        self.assertEqual(pi.model, worker.model)
        self.assertEqual(pi.routing_provider, "vendor-b/fp8")
        self.assertEqual(pi.serving_name, "Vendor B")
        mismatch = False

        def answer(request):
            data = json.loads(request.content)
            if data["stream"]:
                self.assertEqual(data["provider"]["only"], ["vendor-a"])
                record = {"model": "operator/foreground", "provider": "Other" if mismatch else "Vendor A",
                          "choices": [{"delta": {"content": "Hi"}}]}
                return httpx.Response(200, text=f"data: {json.dumps(record)}\n\ndata: [DONE]\n\n")
            self.assertEqual(data["provider"]["only"], ["vendor-b/fp8"])
            return httpx.Response(200, json=completion("operator/worker",
                                  provider="Other" if mismatch else "Vendor B"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            worker.client = foreground.client = client
            self.assertEqual(await foreground.run("Hi", Path(".")), "Hi")
            self.assertEqual(await worker.run("Do job", Path(".")), "Done")
            mismatch = True
            with self.assertRaisesRegex(ValueError, "route"):
                await foreground.run("Hi again", Path("."))
            with self.assertRaisesRegex(ValueError, "route"):
                await worker.run("Do job", Path("."))

    async def test_generic_foreground_uses_exact_model_and_portable_request(self):
        env = QWEN | {
            "ME3_FOREGROUND_PROFILE": "compatible",
            "ME3_FOREGROUND_MODEL": "operator/APUS-OpenJev-4B",
        }
        with patch.dict(os.environ, env, clear=True):
            backend = configured_foreground()

        def answer(request):
            data = json.loads(request.content)
            self.assertEqual(data["model"], env["ME3_FOREGROUND_MODEL"])
            self.assertNotIn("chat_template_kwargs", data)
            self.assertNotIn("provider", data)
            self.assertTrue(data["stream"])
            chunk = {"model": data["model"], "choices": [{"delta": {"content": "Hi"}}]}
            return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            backend.client = client
            self.assertEqual(await backend.run("Hi", Path(".")), "Hi")

    async def test_qwen_worker_and_foreground_use_independent_credentials(self):
        with patch.dict(os.environ, QWEN, clear=True):
            foreground, worker = configured_foreground(), configured_backend()
        self.assertEqual(foreground.config.model, QWEN["ME3_FOREGROUND_MODEL"])

        def answer(request):
            self.assertEqual(str(request.url), "http://localhost:8001/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer worker-only")
            data = json.loads(request.content)
            self.assertEqual(data["model"], QWEN["ME3_WORKER_MODEL"])
            self.assertEqual(data["messages"], [{"role": "user", "content": "Do job"}])
            self.assertEqual(data["chat_template_kwargs"], {"enable_thinking": False})
            self.assertNotIn("tools", data)
            return httpx.Response(200, json=completion(data["model"]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            worker.client = client
            self.assertEqual(await worker.run("Do job", Path(".")), "Done")

    async def test_direct_openrouter_worker_pins_route_and_checks_response(self):
        env = QWEN | ROUTED_WORKER
        del env["ME3_WORKER_BASE_URL"]
        worker = configured_backend(env)
        routes = iter(["Cerebras", "unexpected"])

        def answer(request):
            self.assertEqual(request.headers["Authorization"], "Bearer gateway-only")
            self.assertEqual(str(request.url), OPENROUTER_BASE_URL + "/chat/completions")
            data = json.loads(request.content)
            self.assertEqual(data["provider"], {"only": ["cerebras"],
                                              "allow_fallbacks": False,
                                              "require_parameters": True})
            self.assertEqual(data["reasoning"]["effort"], "medium")
            reply = completion(GPT_OSS, provider=next(routes))
            reply["choices"][0]["message"]["reasoning"] = "private provider trace"
            return httpx.Response(200, json=reply)

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            worker.client = client
            self.assertEqual(await worker.run("Do job", Path(".")), "Done")
            self.assertEqual(worker.verified_provider, "Cerebras")
            with self.assertRaisesRegex(ValueError, "route"):
                await worker.run("Do another job", Path("."))

    async def test_conversation_uses_foreground_while_direct_job_is_blocked(self):
        from me3.runtime import AgentRuntime

        worker = configured_backend(QWEN)
        foreground = configured_foreground(env=QWEN)
        started, release = asyncio.Event(), asyncio.Event()
        requests = []

        async def answer(request):
            body = json.loads(request.content)
            model = body["model"]
            requests.append(model)
            if model == worker.model:
                started.set()
                await release.wait()
                return httpx.Response(200, json=completion(model, "Stored draft."))
            chunk = {"model": model, "choices": [{"delta": {"content": "Hello there."}}]}
            return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            worker.client = foreground.client = client
            with tempfile.TemporaryDirectory() as directory:
                runtime = AgentRuntime(Path(directory), worker, foreground, memory_enabled=False)
                speak = AsyncMock(return_value=True)
                try:
                    session = runtime.open_session(speak, AsyncMock(), owner="Ada")
                    self.assertEqual(await session.accept("background task draft a note"), "delegated")
                    await asyncio.wait_for(started.wait(), timeout=2)
                    self.assertEqual(await session.accept("Hello"), "turn")
                    await asyncio.wait_for(session._active, timeout=2)
                    speak.assert_any_await("Hello there.")
                    job = session.jobs.list()[0]
                    self.assertEqual(job["status"], "running")
                    release.set()
                    await runtime.supervisor.wait(job["id"])
                    self.assertEqual(session.jobs.result(job["id"]), "Stored draft.")
                    self.assertEqual(requests, [worker.model, foreground.config.model])
                finally:
                    release.set()
                    await runtime.close()

    async def test_direct_worker_rejects_incomplete_tool_or_wrong_model_results(self):
        worker = configured_backend(QWEN)
        model = QWEN["ME3_WORKER_MODEL"]
        truncated = completion(model)
        truncated["choices"][0]["finish_reason"] = "length"
        tool = completion(model)
        tool["choices"][0]["message"]["tool_calls"] = [{"type": "function"}]
        for record in [truncated, tool, completion("other"), completion(model, "")]:
            with self.subTest(record=record):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=record)
                )) as client:
                    worker.client = client
                    with self.assertRaises(ValueError):
                        await worker.run("Do job", Path("."))

    async def test_compatible_text_stream_requires_content_and_completion(self):
        env = QWEN | {"ME3_FOREGROUND_PROFILE": "compatible"}
        backend = configured_foreground(env=env)
        chunk = {"model": backend.config.model,
                 "choices": [{"delta": {"content": "Partial"}}]}
        for body in ("data: [DONE]\n\n", f"data: {json.dumps(chunk)}\n\n"):
            with self.subTest(body=body):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, text=body)
                )) as client:
                    backend.client = client
                    with self.assertRaises((ValueError, RuntimeError)):
                        await backend.run("Say hello", Path("."))

    def test_doctor_detects_missing_pi_for_foreground_only(self):
        report = configuration_report(QWEN | {
            "ME3_FOREGROUND_PROFILE": "pi-fast", "ME3_FOREGROUND_PROVIDER": "catalog",
        })
        self.assertIn("foreground", report["blockers"])
        self.assertNotIn("worker model/provider", report["blockers"])

    def test_direct_worker_validates_endpoint_and_role_settings(self):
        for override in [
            {"ME3_WORKER_BASE_URL": ""},
            {"ME3_WORKER_MODEL": " "},
            {"ME3_WORKER_PROVIDER": "unknown"},
            ROUTED_WORKER | {"ME3_WORKER_BASE_URL": "https://elsewhere.invalid"},
            ROUTED_WORKER | {"ME3_WORKER_BASE_URL": "", "ME3_WORKER_MODEL": "other"},
            ROUTED_WORKER | {"ME3_WORKER_BASE_URL": "", "OPENROUTER_API_KEY": ""},
        ]:
            with self.subTest(override=list(override)), self.assertRaises(ValueError):
                configured_backend(QWEN | override)

    def test_doctor_resolves_both_mixed_orders_both_routed_and_pi(self):
        for env in [
            QWEN, QWEN | ROUTED_FG, QWEN | ROUTED_WORKER | {"ME3_WORKER_BASE_URL": ""},
            QWEN | ROUTED_FG | ROUTED_WORKER | {"ME3_WORKER_BASE_URL": ""},
            QWEN | {"ME3_FOREGROUND_PROFILE": "pi-fast", "ME3_FOREGROUND_PROVIDER": "catalog",
                    "ME3_HARNESS": "pi", "ME3_PI_BIN": sys.executable},
        ]:
            with self.subTest(env=(env["ME3_FOREGROUND_PROFILE"], env["ME3_WORKER_PROVIDER"])):
                report = configuration_report(env)
                self.assertNotIn("foreground", report["blockers"])
                self.assertNotIn("worker model/provider", report["blockers"])
                self.assertEqual(report["foreground"]["profile"], env["ME3_FOREGROUND_PROFILE"])
                self.assertEqual(report["worker"]["harness"], env["ME3_HARNESS"])
                self.assertEqual(report["worker"]["model"], env["ME3_WORKER_MODEL"])
                self.assertNotIn("worker-only", json.dumps(report))
