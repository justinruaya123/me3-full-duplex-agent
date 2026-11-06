"""Benchmark stage evidence follows accepted transcripts and valid content."""

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from test_duplex_v1 import Backend, Jobs

from me3.configuration import ForegroundConfig
from me3.duplex import DuplexController
from me3.foreground import ForegroundBackend
from me3.incremental import TranscriptRevision


class StageMarksTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_and_stale_text_cannot_be_marked_as_new_final(self):
        observed = []

        async def speak(text):
            return True

        async def stop():
            pass

        with tempfile.TemporaryDirectory() as directory:
            jobs = Jobs(Path(directory))
            controller = DuplexController(
                jobs, Backend(), speak, stop,
                on_transcript=observed.append,
            )
            try:
                partial = TranscriptRevision(
                    "s", "t", 1, "background task draft", 0, 1
                )
                final = TranscriptRevision(
                    "s", "t", 2, "background task draft", 0, 2, True
                )
                await controller.transcript(partial)
                self.assertFalse(any(event.committed for event in observed))
                self.assertFalse(jobs.list())
                await controller.transcript(final)
                await controller.transcript(final)
                self.assertEqual(sum(e.committed for e in observed), 1)
                self.assertEqual(len(jobs.list()), 1)
                await controller.close()
                await controller.transcript(final)
                self.assertEqual(len(observed), 2)
            finally:
                await controller.close()

    async def test_llm_first_token_is_marked_once_for_valid_text(self):
        events = []
        config = ForegroundConfig("qwen", "http://localhost/v1", "exact", "")
        records = [
            {"model": "exact", "choices": [{"delta": delta}]}
            for delta in ({"role": "assistant"}, {"content": "Hi"},
                          {"content": "."})
        ]
        response = "".join(
            "data: " + json.dumps(record) + "\n\n" for record in records
        ) + "data: [DONE]\n\n"
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=response)
        )) as client:
            backend = ForegroundBackend(
                config, client=client,
                on_stage=lambda name, **fields: events.append((name, fields)),
            )
            answer = "".join([part async for part in backend.stream("Hello")])
        self.assertEqual(answer, "Hi.")
        self.assertEqual([name for name, _ in events],
                         ["llm_request", "llm_first_token"])
        self.assertEqual(events[0][1]["chars"], 5)

    async def test_wrong_model_cannot_publish_a_first_token_mark(self):
        events = []
        config = ForegroundConfig("qwen", "http://localhost/v1", "exact", "")
        record = {"model": "substitute",
                  "choices": [{"delta": {"content": "wrong"}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text="data: " + json.dumps(record) + "\n\n"
            )
        )) as client:
            backend = ForegroundBackend(
                config, client=client,
                on_stage=lambda name, **fields: events.append(name),
            )
            with self.assertRaises(ValueError):
                async for _ in backend.stream("Hello"):
                    pass
        self.assertEqual(events, ["llm_request"])
