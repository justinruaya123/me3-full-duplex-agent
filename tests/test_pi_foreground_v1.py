"""Pi foreground protocol fixtures; not provider/acoustic qualification."""

from pathlib import Path
import sys
import tempfile
import unittest


FIXTURE = '''
import json,sys,time
level = "off"
for line in sys.stdin:
 r=json.loads(line); kind=r["type"]; data={}
 if kind=="get_state":
  data={"model":{"provider":"fixture","id":"exact"},
        "thinkingLevel":LEVEL,"isStreaming":False}
 elif kind=="get_available_thinking_levels": data={"levels":["off"]}
 elif kind=="new_session": data={"cancelled":False}
 elif kind=="prompt": data={"disposition":"started"}
 print(json.dumps({"type":"response","id":r["id"],
                   "success":True,"data":data}),flush=True)
 if kind=="prompt":
  print(json.dumps({"type":"message_update","assistantMessageEvent":
       {"type":"text_delta","delta":"Hello."}}),flush=True)
  if r["message"]=="block": time.sleep(30)
  if r["message"]=="reason":
   print(json.dumps({"type":"message_update","assistantMessageEvent":
        {"type":"thinking_delta","delta":"private"}}),flush=True)
  else:
   print(json.dumps({"type":"message_end","message":
        {"role":"assistant","provider":"fixture","model":"exact",
         "stopReason":"stop",
         "content":[{"type":"text","text":"Hello."}]}}),flush=True)
  print(json.dumps({"type":"agent_settled"}),flush=True)
'''


class PiForegroundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    def backend(self, level='"off"', transform=lambda source: source):
        from me3.pi_foreground import PiForegroundBackend
        child = self.root / "fixture.py"
        child.write_text(transform(FIXTURE.replace("LEVEL", level)))
        backend = PiForegroundBackend(
            (sys.executable, str(child)), provider="fixture", model="exact",
            timeout=3,
        )
        self.addAsyncCleanup(backend.close)
        return backend

    async def routed(self, *chunks, fail=False):
        async def stream(prompt):
            for chunk in chunks:
                yield chunk
            if fail:
                raise RuntimeError("provider failed")

        backend = self.backend()
        backend.stream = stream
        return [item async for item in backend.stream_turn("context", "owner request")]

    async def test_voice_action_markers_are_never_spoken(self):
        from me3.foreground import ActionProposal
        self.assertEqual(await self.routed(" ", "Hello", "."), ["Hello", "."])
        for kind in ("lookup", "submit", "website"):
            self.assertEqual(await self.routed(" @", kind), [ActionProposal(kind, "owner request")])
        for invalid in ("@unknown", "@submit\nextra", " "):
            with self.assertRaises(ValueError):
                await self.routed(invalid)
        with self.assertRaises(RuntimeError):
            await self.routed("@submit", fail=True)

    async def test_streams_and_reuses_process_without_reusing_context(self):
        backend = self.backend()
        try:
            self.assertEqual(await backend.run("hi", self.root), "Hello.")
            process = backend.process
            self.assertEqual(await backend.run("again", self.root), "Hello.")
            self.assertIs(backend.process, process)
        finally:
            await backend.close()

    async def test_clamped_reasoning_is_explicit_failure(self):
        backend = self.backend('"minimal"')
        with self.assertRaisesRegex(ValueError, "reasoning"):
            await backend.run("hi", self.root)
        self.assertIsNone(backend.process)

    async def test_reasoning_delta_is_not_spoken(self):
        backend = self.backend()
        with self.assertRaisesRegex(ValueError, "reasoning"):
            await backend.run("reason", self.root)
        self.assertIsNone(backend.process)

    async def test_early_close_reaps_inflight_process(self):
        backend = self.backend()
        stream = backend.stream("block")
        self.assertEqual(await anext(stream), "Hello.")
        process = backend.process
        await stream.aclose()
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(backend.process)

    async def test_response_model_change_fails_and_reaps(self):
        backend = self.backend(transform=lambda source: source.replace(
            '"model":"exact"', '"model":"wrong"'
        ))
        with self.assertRaisesRegex(ValueError, "response model"):
            await backend.run("hi", self.root)
        self.assertIsNone(backend.process)

    async def test_failed_assistant_message_is_not_success(self):
        backend = self.backend(transform=lambda source: source.replace(
            '"stopReason":"stop"', '"stopReason":"error"'
        ))
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            await backend.run("hi", self.root)
        self.assertIsNone(backend.process)

    async def test_unsupported_off_is_not_silently_minimal(self):
        backend = self.backend(transform=lambda source: source.replace(
            '"levels":["off"]', '"levels":["minimal"]'
        ))
        with self.assertRaisesRegex(ValueError, "disable reasoning"):
            await backend.run("hi", self.root)
        self.assertIsNone(backend.process)

    async def test_timeout_reaps_process(self):
        backend = self.backend()
        backend.timeout = 0.2
        with self.assertRaises(TimeoutError):
            await backend.run("block", self.root)
        self.assertIsNone(backend.process)


class PiForegroundConfigTests(unittest.TestCase):
    def test_explicit_profile_requires_own_model_selection(self):
        from me3.configuration import ForegroundConfig
        with self.assertRaises(ValueError):
            ForegroundConfig.from_env({"ME3_FOREGROUND_PROFILE": "pi-fast",
                                       "ME3_WORKER_MODEL": "worker"})

    def test_profile_needs_no_qwen_endpoint(self):
        from me3.configuration import ForegroundConfig
        config = ForegroundConfig.from_env({
            "ME3_FOREGROUND_PROFILE": "pi-fast",
            "ME3_FOREGROUND_PROVIDER": "fixture",
            "ME3_FOREGROUND_MODEL": "exact",
        })
        self.assertEqual(config.profile, "pi-fast")
        self.assertEqual(config.provider, "fixture")
