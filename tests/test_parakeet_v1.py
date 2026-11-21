import asyncio
import time
import unittest

from me3.parakeet import Utterance


class ParakeetTests(unittest.IsolatedAsyncioTestCase):
    async def test_revisions_replace_and_only_expected_final_completes(self):
        events = []
        u = Utterance(lambda kind, **data: events.append((kind, data)))
        u.accept(dict(type="partial", id=u.id, revision=1, text="Thu"))
        u.accept(dict(type="partial", id=u.id, revision=2, text="Tuesday"))
        u.accept(dict(type="partial", id=u.id, revision=1, text="Thu"))
        self.assertEqual([e[1]["text"] for e in events], ["Thu", "Tuesday"])
        u.accept(dict(type="final", id="old", revision=7, text="wrong"))
        self.assertFalse(u.done.done())
        with self.assertRaises(ValueError):
            u.accept(dict(type="final", id=u.id, revision=3, text="early"))
        u.expect = "final"
        u.accept(dict(type="final", id=u.id, revision=3, text="Tuesday"))
        self.assertEqual(u.done.result(), "Tuesday")
        self.assertNotIn("commit", [e[0] for e in events])

    async def test_cancel_ack_and_empty_final_are_distinct(self):
        a = Utterance(lambda *args, **kwargs: None)
        b = Utterance(lambda *args, **kwargs: None)
        self.assertNotEqual(a.id, b.id)
        a.expect = "canceled"
        a.accept(dict(type="canceled", id=a.id))
        self.assertIsNone(a.done.result())
        b.expect = "final"
        b.accept(dict(type="final", id=b.id, revision=1, text=""))
        self.assertEqual(b.done.result(), "")


class StreamTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_paced_binary_replacement_cancel_and_new_session(self):
        import aiohttp
        from aiohttp import web
        from unittest.mock import patch
        from me3.parakeet import FRAME, MODEL, Stream

        wire = []

        async def handle(request):
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            self.assertNotIn("Origin", request.headers)
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json(dict(type="ready", version=1, model=MODEL, sample_rate=16000))
            current = None
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self.assertEqual(len(msg.data), FRAME)
                    wire.append("audio")
                    await ws.send_json(dict(type="partial", id=current, revision=1, text="sample"))
                else:
                    event = msg.json()
                    wire.append(event["type"])
                    if event["type"] == "start":
                        self.assertIsNone(current)
                        current = event["id"]
                    else:
                        self.assertEqual(current, event["id"])
                        if event["type"] == "end":
                            await ws.send_json(dict(type="final", id=current, revision=2, text=""))
                        else:
                            await ws.send_json(dict(type="canceled", id=current))
                        current = None
            return ws

        app = web.Application()
        app.router.add_get("/asr", handle)
        from aiohttp.test_utils import TestServer
        async with TestServer(app) as server, aiohttp.ClientSession() as client:
            with patch("me3.parakeet.URL", str(server.make_url("/asr")).replace("http:", "ws:")):
                ids = []
                for _ in range(2):
                    partial = asyncio.Event()
                    stream = Stream(client, lambda kind, **kw: partial.set() if kind == "partial" else None,
                                    "test-only")
                    try:
                        await stream.connect()
                        ids.append((await stream.begin()).id)
                        await stream.audio(bytes(FRAME))
                        await asyncio.wait_for(partial.wait(), 1)
                        self.assertIsNone(await stream.finish(cancel=True))
                        ids.append((await stream.begin()).id)
                        await stream.audio(bytes(FRAME))
                        self.assertEqual(await stream.finish(), "")
                    finally:
                        await stream.close()
                self.assertEqual(len(set(ids)), 4)
                self.assertEqual(wire, ["start","audio","cancel","start","audio","end"] * 2)


class LocalPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_policy_controls_dispatch_and_incomplete_input_is_canceled(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from pipecat.audio.vad.vad_analyzer import VADState
        from me3.parakeet import FRAME
        from me3.parakeet_voice import local_turns

        async def frames():
            for _ in range(170):
                yield bytes(FRAME)
                await asyncio.sleep(0)

        class Wire:
            current = None

            async def begin(self):
                self.current = SimpleNamespace(id="u", frames=0)
                return self.current

            async def audio(self, frame):
                self.current.frames += 1

            async def finish(self, *, cancel=False):
                self.current = None
                self.canceled = cancel
                return None if cancel else result

        for complete, result, talking, awaiting_answer, expected in [
            (False, "build the page", False, False, False), (True, "", False, False, False),
            (True, "yeah", True, False, False), (True, "build the page", False, False, True),
            (True, "Yeah.", False, False, False), (True, "Yes.", False, True, True),
            (True, "I see.", False, False, False), (True, "Ahh.", False, True, False),
            (True, "Got it.", False, True, True), (True, "Ah?", False, True, True),
            (True, "I see a problem.", True, False, True),
            (True, "No, Tuesday.", True, False, True),
        ]:
            with self.subTest(complete=complete, result=result, talking=talking):
                wire = Wire()
                vad = SimpleNamespace(analyze_audio=AsyncMock(side_effect=[
                    VADState.SPEAKING, *([VADState.QUIET] * 169)]))
                playback = SimpleNamespace(device=None, task=Mock(done=lambda: False) if talking else None,
                                           epoch=2, hold=Mock(), cut=AsyncMock(), observe_output=Mock(),
                                           awaiting_answer=awaiting_answer, allow_cue=not awaiting_answer,
                                           last_reply_end=time.monotonic())
                with patch("me3.parakeet_voice.emit") as emit:
                    await local_turns(wire, frames(), vad, AsyncMock(return_value=complete), playback)
                commits = [e for e in emit.call_args_list if e.args == ("commit",)]
                self.assertEqual(len(commits), int(expected))
                self.assertEqual(wire.canceled, not complete)
                if commits:
                    self.assertEqual(commits[0].kwargs["text"], result)

    def test_render_tail_cannot_authorize_an_overlapping_short_transcript(self):
        from me3.parakeet_voice import NearEndSpeech
        gate = NearEndSpeech()
        gate.start(10., last_output=9.98)
        gate.observe(9.99, True)
        gate.observe(10.18, True)
        gate.observe(10.35, False)
        self.assertFalse(gate.clear)
        for t in (10.40, 10.42, 10.44):
            gate.observe(t, True)
        self.assertTrue(gate.clear)
        gate.start(20., last_output=10.)
        self.assertTrue(gate.clear)

    def test_overflow_abandons_input_through_bounded_reconnect_path(self):
        from me3.parakeet import Stream, TransientASRError
        with self.assertRaisesRegex(TransientASRError, "audio_overflow"):
            Stream.server_error({"type":"error","code":"audio_overflow","id":"u1"})
        with self.assertRaises(ValueError):
            Stream.server_error({"type":"error","code":"bad_frame","id":"u1"})
