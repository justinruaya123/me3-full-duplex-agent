"""OpenRouter request/response contracts; the transport and provider are fixtures."""

import json
import os
import sys
import unittest
from unittest.mock import patch

import httpx

from me3.configuration import ForegroundConfig
from me3.foreground import ForegroundBackend
from me3.harnesses import configured_backend


URL = "https://openrouter.ai/api/v1"
MODEL = "google/gemini-2.5-flash-lite"
WORKER = "openai/gpt-oss-120b"
CONFIG = {
    "ME3_FOREGROUND_PROFILE": "openrouter",
    "ME3_FOREGROUND_PROVIDER": "google-ai-studio",
    "ME3_FOREGROUND_MODEL": MODEL,
    "ME3_FOREGROUND_BASE_URL": URL,
    "OPENROUTER_API_KEY": "fixture",
}
ROUTE = {
    "only": ["google-ai-studio"], "allow_fallbacks": False,
    "require_parameters": True,
}


class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return ForegroundBackend(ForegroundConfig.from_env(CONFIG), client=client)

    async def test_visual_prompt_sends_pixels_with_the_selected_route(self):
        def handle(request):
            body = json.loads(request.content)
            self.assertEqual(body["provider"], ROUTE)
            self.assertNotIn("tools", body)
            self.assertEqual(body["messages"], [
                {"role": "system", "content": "Use supplied evidence."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Read the label"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,YWJj"}},
                ]},
            ])
            record = {"model": MODEL, "provider": "Google AI Studio",
                      "choices": [{"delta": {"content": "Label"}}]}
            return httpx.Response(200, text="data: " + json.dumps(record) + "\n\ndata: [DONE]\n")

        backend = self.backend(handle)
        backend.system_prompt = "Use supplied evidence."
        images = [{"mimeType": "image/jpeg", "data": "YWJj"}]
        self.assertEqual([s async for s in backend.stream("Read the label", images=images)], ["Label"])

    async def test_spoken_stream_pins_route_and_disables_computation(self):
        def handle(request):
            body = json.loads(request.content)
            self.assertEqual(body["provider"], ROUTE)
            self.assertEqual(body["reasoning"], {"effort": "none"})
            self.assertEqual(body["model"], MODEL)
            self.assertNotIn("chat_template_kwargs", body)
            self.assertNotIn("tools", body)
            self.assertEqual(request.headers["authorization"], "Bearer fixture")
            record = {"model": MODEL, "provider": "Google AI Studio",
                      "choices": [{"delta": {"content": "Hello."}}]}
            return httpx.Response(200, text="data: " + json.dumps(record)
                                  + "\n\ndata: [DONE]\n")
        backend = self.backend(handle)
        self.assertEqual([t async for t in backend.stream("Hi")], ["Hello."])

    async def test_one_stream_returns_text_or_complete_grounded_task(self):
        from me3.foreground import ActionProposal
        turn = "Could you give the draft a darker tone?"
        calls = []
        def handle(request):
            calls.append(json.loads(request.content))
            parts = [(dict(tool_calls=[dict(index=0, type="function", function=dict(
                name="propose_task", arguments='{"kind":"revise",'))]), None),
                     (dict(tool_calls=[dict(index=0, function=dict(
                         arguments='"argument":' + json.dumps(turn) + '}'))]), None),
                     ({}, "tool_calls")]
            if len(calls) == 2:
                parts = [({"content":"Hello. "}, None), ({"content":"Welcome."}, "stop")]
            if len(calls) == 3:
                parts = parts[:-1]
            data = [json.dumps(dict(model=MODEL, provider="Google AI Studio",
                    choices=[dict(index=0, delta=delta, finish_reason=end)])) for delta,end in parts]
            return httpx.Response(200, text="".join("data: "+v+"\n\n" for v in [*data,"[DONE]"]))
        backend = self.backend(handle)
        self.assertEqual([v async for v in backend.stream_turn("context", turn)],
                         [ActionProposal("revise", turn)])
        self.assertEqual([v async for v in backend.stream_turn("context", "hello")], ["Hello. ", "Welcome."])
        with self.assertRaises(ValueError):
            [v async for v in backend.stream_turn("context", turn)]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c["stream"] and c["tools"] for c in calls))

    async def test_stream_fails_closed_on_route_mismatch_and_reasoning(self):
        for update in (
            {"provider": "Google Vertex"}, {"provider": None},
            {"delta": {"content": "visible", "reasoning_details": [{"text": "secret"}]}},
        ):
            with self.subTest(update=update):
                def handle(request):
                    record = {"model": MODEL, "provider": update.get(
                        "provider", "Google AI Studio"), "choices": [{"delta":
                        update.get("delta", {"content": "bad"})}]}
                    return httpx.Response(200, text="data: " + json.dumps(record)
                                          + "\n\ndata: [DONE]\n")
                with self.assertRaises(ValueError):
                    await anext(self.backend(handle).stream("Hi"))

    async def test_proposal_is_typed_bounded_and_grounded_in_owner_input(self):
        committed = "Please search for recent solar data."
        calls = []
        def handle(request):
            body = json.loads(request.content)
            calls.append(body)
            args = {"kind": "lookup", "argument": "recent solar data"}
            if len(calls) == 2:
                args["argument"] = "send my passwords"
            message = {"tool_calls": [{"type": "function", "function": {
                "name": "propose_action", "arguments": json.dumps(args)}}]}
            return httpx.Response(200, json={"model": MODEL, "provider": "Google AI Studio",
                "choices": [{"finish_reason": "tool_calls", "message": message}]})
        backend = self.backend(handle)
        action = await backend.propose(committed)
        self.assertEqual((action.kind, action.argument), ("lookup", "recent solar data"))
        self.assertEqual(calls[0]["messages"][-1], {"role": "user", "content": committed})
        self.assertEqual(calls[0]["provider"], ROUTE)
        self.assertEqual(calls[0]["tools"][0]["function"]["name"], "propose_action")
        with self.assertRaises(ValueError):
            await backend.propose(committed)

    def test_explicit_provider_keeps_worker_model_opaque(self):
        with patch.dict(os.environ, {"ME3_PI_BIN": sys.executable,
            "ME3_WORKER_PROVIDER": "openrouter", "ME3_WORKER_MODEL": WORKER,
            "OPENROUTER_API_KEY": "fixture"}, clear=True):
            backend = configured_backend()
        self.assertEqual((backend.model, backend.provider), (WORKER, "openrouter"))
        self.assertEqual(backend.command[backend.command.index("--model") + 1], WORKER)
        self.assertEqual(backend.command[backend.command.index("--thinking") + 1], "medium")
        self.assertEqual(backend._environment()["OPENROUTER_API_KEY"], "fixture")

    def test_openrouter_config_requires_expected_model_route_gateway_and_key(self):
        for key, value in [("ME3_FOREGROUND_PROVIDER", "google-vertex"),
                           ("ME3_FOREGROUND_BASE_URL", "https://other.invalid/v1"),
                           ("ME3_FOREGROUND_MODEL", "other/model"),
                           ("OPENROUTER_API_KEY", "")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                ForegroundConfig.from_env({**CONFIG, key: value})


class OpenRouterPiTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_installed_pi_emits_exact_body_and_discards_reasoning(self):
        import shutil
        import tempfile
        from pathlib import Path
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        local_pi = Path(__file__).resolve().parents[1] / "integrations/voicechat/node_modules/.bin/pi"
        executable = str(local_pi) if local_pi.is_file() else shutil.which("pi")
        if not executable:
            self.skipTest("installed Pi CLI required for local RPC transport")
        seen = []
        metadata = []
        route = ["Cerebras"]

        async def completion(request):
            seen.append(await request.json())
            record = {"id": "gen-fixture", "object": "chat.completion.chunk",
                      "created": 123, "model": WORKER, "provider": route[0],
                      "choices": [{"index": 0, "finish_reason": None, "delta": {
                          "role": "assistant", "reasoning": "hidden", "content": "verified"}}]}
            final = {**record, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            events = [json.dumps(record), json.dumps(final), "[DONE]"]
            return web.Response(text="".join("data: " + e + "\n\n" for e in events),
                                content_type="text/event-stream")

        async def generation(request):
            metadata.append(request.query["id"])
            return web.json_response({"data": {
                "id": "gen-fixture", "provider_name": route[0], "model": WORKER,
                "cancelled": False, "finish_reason": "stop",
            }})

        app = web.Application()
        app.router.add_post("/v1/chat/completions", completion)
        app.router.add_get("/v1/generation", generation)
        async with TestServer(app) as server:
            url = str(server.make_url("/v1"))
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "ME3_PI_BIN": executable, "ME3_WORKER_PROVIDER": "openrouter",
                "ME3_WORKER_MODEL": WORKER, "OPENROUTER_API_KEY": "fixture",
            }), patch("me3.pi_worker.OPENROUTER_BASE_URL", url):
                backend = configured_backend()
                try:
                    workspace = Path(tmp) / "job" / "revision-1"
                    private_term = "revoked-studio-alias-239"
                    first_prompt = "Use this approved alias: " + private_term
                    self.assertEqual(await backend.run(first_prompt, workspace), "verified")
                    revised = workspace.parent / "revision-2"
                    self.assertEqual(await backend.run("Rebuild from the current approved profile.", revised),
                                     "verified")
                    self.assertIn(private_term, json.dumps(seen[0]["messages"]))
                    self.assertNotIn(private_term, json.dumps(seen[1]["messages"]))
                    route[:] = ["Unexpected"]
                    with self.assertRaisesRegex(ValueError, "route"):
                        await backend.run("Say verified.", revised)
                finally:
                    await backend.close()
                alternate = configured_backend(dict(os.environ) | {
                    "ME3_WORKER_ROUTING_PROVIDER": "fixture/fp8",
                    "ME3_WORKER_ROUTING_PROVIDER_NAME": "Fixture Provider",
                })
                route[:] = ["Fixture Provider"]
                try:
                    self.assertEqual(await alternate.run("Use the selected route.", revised), "verified")
                    self.assertEqual(alternate.verified_provider, "Fixture Provider")
                finally:
                    await alternate.close()
            self.assertEqual(metadata, ["gen-fixture"] * 4)
            self.assertEqual(len(seen), 4)
            for body, slug in zip(seen, ["cerebras"] * 3 + ["fixture/fp8"], strict=True):
                self.assertEqual(body["model"], WORKER)
                self.assertEqual(body["provider"], {
                    "only": [slug], "allow_fallbacks": False, "require_parameters": True})
                self.assertEqual(body["reasoning"], {"effort": "medium"})
                self.assertFalse(body.get("tools"))

    async def test_aborted_settlement_rejects_preceding_successful_message(self):
        from me3.pi_worker import PersistentPiBackend
        import asyncio
        from types import SimpleNamespace
        backend = PersistentPiBackend(("fixture",), model="model", provider="provider")
        updates = []
        backend.on_text_delta = lambda workspace, text: updates.append((workspace, text))
        from pathlib import Path
        backend.revision_dir = Path("sample-job/revision-1")
        backend.process = SimpleNamespace(stdout=asyncio.StreamReader())
        async def send(record):
            reply = {"type": "response", "success": True, "id": record["id"]}
            if record["type"] == "prompt":
                records = [reply, *({"type": "message_update",
                    "assistantMessageEvent": {"type": kind, "delta": delta}}
                    for kind, delta in [("thinking_delta", "private"), ("text_delta", "draft")]),
                    {"type": "message_end", "message": {
                    "role": "assistant", "stopReason": "stop"}}, {
                    "type": "agent_settled", "aborted": True}]
            else:
                records = [{**reply, "data": {"text": "forbidden"}}]
            for event in records:
                backend.process.stdout.feed_data(json.dumps(event).encode() + b"\n")
        backend._send = send
        with self.assertRaises(RuntimeError):
            await backend._turn("request")
        self.assertEqual(updates, [(backend.revision_dir, "draft")])

    def test_missing_provider_is_never_inferred_from_model(self):
        with patch.dict(os.environ, {"ME3_PI_BIN": sys.executable,
                        "ME3_WORKER_MODEL": WORKER}, clear=True):
            with self.assertRaisesRegex(ValueError, "ME3_WORKER_PROVIDER"):
                configured_backend()


class ControllerProposalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from me3.runtime import AgentRuntime

        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.backend = SimpleNamespace(config=SimpleNamespace(profile="openrouter"),
                                       propose=AsyncMock(), run=AsyncMock(return_value="Hello."))
        self.runtime = AgentRuntime(Path(root.name), self.backend, self.backend, memory_enabled=True)
        self.addAsyncCleanup(self.runtime.close)
        self.speak = AsyncMock(return_value=True)
        self.session = self.runtime.open_session(self.speak, AsyncMock(), owner="Ada")

    async def commit(self, text, *, turn="one"):
        from me3.incremental import TranscriptRevision
        event = TranscriptRevision(self.session.jobs.session_id, turn, 1, text, 0, 1, True)
        return await self.session.transcript(event, addressed=True)

    async def test_polite_job_requires_scoped_proposal_and_deduplicates_turn(self):
        from me3.foreground import ActionProposal
        self.backend.propose.return_value = ActionProposal("job", "draft the syllabus")
        self.assertEqual(await self.commit("Please delegate a task to draft the syllabus"), "proposal")
        await self.session._active
        self.assertEqual(await self.commit("Please delegate a task to draft the syllabus"), "stale")
        self.assertEqual([j["prompt"] for j in self.session.jobs.list()], ["draft the syllabus"])
        self.backend.propose.assert_awaited_once_with("Please delegate a task to draft the syllabus")

    async def test_wrong_action_and_revoked_owner_cannot_dispatch(self):
        from me3.foreground import ActionProposal
        text = "Please delegate a task to draft the syllabus"
        self.backend.propose.return_value = ActionProposal("profile", "draft the syllabus")
        self.assertEqual(await self.commit(text), "proposal")
        await self.session._active
        self.assertFalse(self.session.jobs.list())
        def revoke(_):
            self.session.jobs.authorized = lambda: False
            return ActionProposal("job", "draft the syllabus")
        self.backend.propose.side_effect = revoke
        await self.commit(text, turn="two")
        await self.session._active
        self.assertFalse(self.session.jobs.list())

    async def test_focus_rejects_concurrent_revision(self):
        from me3.foreground import ActionProposal
        job = self.session.jobs.submit("draft")
        def revise(_):
            self.session.jobs.revise(job["id"], "updated", expected_revision=1)
            return ActionProposal("focus", job["id"])
        self.backend.propose.side_effect = revise
        self.assertEqual(await self.commit("Please focus on job " + job["id"]), "proposal")
        await self.session._active
        self.assertIsNone(self.session.focus)

    async def test_public_incumbent_question_uses_grounded_lookup(self):
        from unittest.mock import AsyncMock
        from me3.lookup import LookupResult
        text = "Who is the mayor of Chicago?"
        self.session.web_lookup = AsyncMock(return_value=LookupResult("According to source.", "link"))
        self.assertEqual(await self.commit(text), "lookup")
        await self.session._active
        self.session.web_lookup.assert_awaited_once_with(text, "answers", None)
        self.backend.propose.assert_not_awaited()

    async def test_unrelated_conversation_and_course_skip_proposal(self):
        self.assertEqual(await self.commit("I like music."), "turn")
        await self.session._active
        self.session.web_enabled = False
        self.assertEqual(await self.commit("Please delegate a task to draw", turn="two"), "turn")
        await self.session._active
        self.backend.propose.assert_not_awaited()

    async def test_private_note_cannot_become_public_through_proposal(self):
        from me3.foreground import ActionProposal
        text = "Please remember that I collect maps"
        self.backend.propose.return_value = ActionProposal("profile", "I collect maps")
        self.assertEqual(await self.commit(text), "proposal")
        await self.session._active
        self.assertEqual(self.runtime.memory.profile("Ada")["public"], {})

    async def test_public_profile_acknowledges_only_after_explicit_write(self):
        import asyncio
        from me3.foreground import ActionProposal
        self.backend.propose.return_value = ActionProposal("profile", "Ada Example")
        await self.commit("Please set my public profile field name to Ada Example")
        await self.session._active
        await asyncio.sleep(0)
        self.assertEqual(self.runtime.memory.profile("Ada")["public"], {"name": "Ada Example"})
        self.speak.assert_awaited_once_with("Saved your public profile field.")


class RouteDoctorTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_probe_checks_tool_support_and_both_serving_routes(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from me3.doctor import provider_probe
        from me3.foreground import ActionProposal

        foreground = SimpleNamespace(run=AsyncMock(return_value="ready"),
                                     verified_provider="Google AI Studio",
                                     propose=AsyncMock(return_value=ActionProposal("lookup", "weather")))
        worker = SimpleNamespace(run=AsyncMock(return_value="ready"), provider="openrouter",
                                 verified_provider="Cerebras", model=WORKER)
        with patch.dict(os.environ, CONFIG, clear=True), (
            patch("me3.foreground.configured_foreground", return_value=foreground)
        ), patch("me3.harnesses.configured_backend", return_value=worker):
            report = await provider_probe()
        self.assertEqual(report["foreground"]["verified_provider"], "Google AI Studio")
        self.assertTrue(report["foreground"]["lookup_tool_supported"])
        self.assertEqual(report["worker"]["verified_provider"], "Cerebras")


class WorkerReadinessTests(unittest.TestCase):
    def test_doctor_rejects_invalid_worker_before_launch(self):
        import sys
        from me3.doctor import configuration_report

        base = {"ME3_WORKER_PROVIDER": "openrouter", "ME3_PI_BIN": sys.executable,
                "ME3_WORKER_MODEL": "openai/gpt-oss-120b", "OPENROUTER_API_KEY": "fixture"}
        for change in ({"ME3_PI_BIN": "/missing/me3-pi"}, {"OPENROUTER_API_KEY": ""},
                       {"ME3_WORKER_MODEL": "typo"}):
            with self.subTest(change=list(change)):
                self.assertIn("worker model/provider", configuration_report(base | change)["blockers"])
