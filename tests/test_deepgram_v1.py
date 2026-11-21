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
    async def test_failed_standby_does_not_interrupt_the_current_turn(self):
        import asyncio
        from unittest.mock import AsyncMock, Mock
        from me3.deepgram import DeepgramStream
        from me3.parakeet import TransientASRError, Utterance

        stream = DeepgramStream(None, Mock(), "test")
        stream.current = Utterance(Mock())
        stream.ws = Mock()
        stream.open_socket = AsyncMock(side_effect=TransientASRError("offline"))
        stream.released = asyncio.Event()
        stream.prepare_next(stream.released)
        async def final(_):
            await asyncio.sleep(.01)
            turn = stream.current
            turn.accept(dict(type="final", id=turn.id, revision=1, text="first turn"))
        stream.ws.send_json = final
        self.assertEqual(await stream.finish(), "first turn")
        self.assertFalse(stream.fault.done())
        with self.assertRaisesRegex(TransientASRError, "offline"):
            await stream.begin()

    async def test_next_handshake_overlaps_final_without_reusing_its_transcript(self):
        import asyncio
        import aiohttp
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        from me3.deepgram import DeepgramStream
        from me3.parakeet import FRAME

        connections = []
        close_requested, release = asyncio.Event(), asyncio.Event()
        async def listen(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            connections.append(ws)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT and msg.json()["type"] == "CloseStream":
                    close_requested.set()
                    await release.wait()
                    await ws.send_json({"type":"Results", "is_final":True, "channel":{
                        "alternatives":[{"transcript":"first turn"}]}})
                    await ws.send_json({"type":"Metadata"})
                    break
            return ws

        app = web.Application()
        app.router.add_get("/", listen)
        async with TestServer(app) as server, aiohttp.ClientSession() as client:
            stream = DeepgramStream(client, lambda *args, **fields: None, "test")
            stream.url = str(server.make_url("/")).replace("http:", "ws:")
            await stream.connect()
            first = await stream.begin()
            await stream.audio(bytes(FRAME))
            try:
                # A slow handshake gets the whole first turn to complete.
                async with asyncio.timeout(.5):
                    while len(connections) < 2:
                        await asyncio.sleep(.005)
            except BaseException:
                await stream.close()
                raise
            final = asyncio.create_task(stream.finish())
            try:
                await asyncio.wait_for(close_requested.wait(), 1)
                self.assertIs(stream.current, first)
                release.set()
                self.assertEqual(await final, "first turn")
                self.assertEqual((await stream.begin()).text, "")
            finally:
                release.set()
                await asyncio.gather(final, return_exceptions=True)
                await stream.close()

    async def test_open_timeout_names_the_provider_and_can_be_retried(self):
        from unittest.mock import AsyncMock, Mock
        from me3.deepgram import DeepgramStream
        from me3.parakeet import TransientASRError

        client = Mock(ws_connect=AsyncMock(side_effect=TimeoutError))
        stream = DeepgramStream(client, Mock(), "test")
        with self.assertRaisesRegex(TransientASRError, "Deepgram connection timed out"):
            await stream.connect()

    async def test_close_stream_flushes_only_matching_utterance_and_cancel_isolated(self):
        import asyncio
        import aiohttp
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        from me3.deepgram import DeepgramStream
        from me3.parakeet import FRAME

        connected = asyncio.Queue()

        async def listen(request):
            self.assertEqual(request.headers["Authorization"], "Token test-only")
            self.assertEqual(request.query["model"], "nova-3")
            self.assertEqual(request.query["endpointing"], "250")
            self.assertIn("keyterm", request.query)
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            connected.put_nowait(True)
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
                await connected.get()
                await stream.begin()
                await stream.audio(bytes(FRAME))
                self.assertIsNone(await stream.finish(cancel=True))
                turn = await stream.begin()
                await connected.get()
                await stream.audio(bytes(FRAME))
                await stream.flush_words()
                self.assertFalse(turn.done.done())
                self.assertEqual(await stream.finish(), "settled final words")
                self.assertEqual(turn.finalized_frames, 1)
                self.assertEqual(turn.endpoint_frames, 1)
                self.assertEqual(turn.settled_text, "settled")
                self.assertEqual([e["id"] for k, e in events if k == "final"], [turn.id])
                await asyncio.wait_for(connected.get(), 1)
                next_turn = await stream.begin()
                await stream.flush_words()
                async with asyncio.timeout(1):
                    while not next_turn.endpoint_frames:
                        await asyncio.sleep(.005)
                next_turn.text = "settled and one more word"
                with self.assertRaisesRegex(RuntimeError, "matching"):
                    stream.finish_endpoint()
                next_turn.text = next_turn.settled_text
                self.assertEqual(stream.finish_endpoint(), "settled")
                await asyncio.wait_for(connected.get(), 1)
                self.assertTrue(next_turn.done.done())
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
