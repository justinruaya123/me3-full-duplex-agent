import unittest

from me3.deepgram import Results


class DeepgramTests(unittest.TestCase):
    def test_final_segments_accumulate_but_interims_replace(self):
        r = Results()
        def segment(words, final):
            return {"type": "Results", "channel": {"alternatives": [{"transcript": words}]},
                    "is_final": final}
        self.assertEqual(r.update(segment("take", False)), "take")
        self.assertEqual(r.update(segment("make a note", True)), "make a note")
        self.assertEqual(r.update(segment("on Monday", False)), "make a note on Monday")
        self.assertEqual(r.update(segment("on Friday", True)), "make a note on Friday")
        self.assertEqual(r.final, "make a note on Friday")


class DeepgramTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_stream_flushes_only_matching_utterance_and_cancel_isolated(self):
        import aiohttp
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        from me3.deepgram import DeepgramStream
        from me3.parakeet import FRAME

        async def listen(request):
            self.assertEqual(request.headers["Authorization"], "Token test-only")
            self.assertEqual(request.query["model"], "nova-3")
            self.assertEqual(request.query["endpointing"], "600")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self.assertEqual(len(msg.data), FRAME)
                    await ws.send_json({"type": "Results", "is_final": False,
                                        "channel": {"alternatives": [{"transcript": "tentative"}]}})
                elif msg.json()["type"] == "Finalize":
                    await ws.send_json({"type": "Results", "is_final": True, "speech_final": True, "start": 0.,
                                        "duration": .02, "channel": {"alternatives": [
                                            {"transcript": "settled"}]}})
                    await ws.send_json({"type": "Results", "is_final": True, "speech_final": True,
                                        "start": .02, "duration": 5.,
                                        "channel": {"alternatives": [{"transcript": ""}]}})
                else:
                    self.assertEqual(msg.json()["type"], "CloseStream")
                    await ws.send_json({"type": "Results", "is_final": True,
                                        "channel": {"alternatives": [{"transcript": "final words"}]}})
                    await ws.send_json({"type": "Metadata"})
                    break
            return ws

        app = web.Application()
        app.router.add_get("/listen", listen)
        async with TestServer(app) as server, aiohttp.ClientSession() as client:
            events = []
            stream = DeepgramStream(client, lambda kind, **data: events.append((kind, data)), "test-only")
            stream.url = str(server.make_url("/listen")).replace("http:", "ws:")
            try:
                await stream.connect()
                await stream.begin()
                await stream.audio(bytes(FRAME))
                self.assertIsNone(await stream.finish(cancel=True))
                turn = await stream.begin()
                await stream.audio(bytes(FRAME))
                await stream.flush_words()
                self.assertFalse(turn.done.done())
                self.assertEqual(await stream.finish(), "settled final words")
                self.assertEqual(turn.finalized_frames, 1)
                self.assertEqual(turn.endpoint_frames, 1)
                self.assertEqual(turn.settled_text, "settled")
                self.assertEqual([e["id"] for k, e in events if k == "final"], [turn.id])
            finally:
                await stream.close()

    async def test_live_capture_can_send_queued_preroll_without_a_second_clock(self):
        from unittest.mock import AsyncMock, Mock, patch
        from me3.deepgram import DeepgramStream
        from me3.parakeet import Utterance, FRAME

        stream = DeepgramStream(None, Mock(), "test")
        stream.current = Utterance(Mock())
        stream.ws = AsyncMock()
        with patch("me3.parakeet.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await stream.audio(bytes(FRAME))
            await stream.audio(bytes(FRAME))
            sleep.assert_not_awaited()
        self.assertEqual(stream.current.frames, 2)
        self.assertEqual(stream.ws.send_bytes.await_count, 2)
