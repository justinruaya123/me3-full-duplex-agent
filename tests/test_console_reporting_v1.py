"""Trusted console stdin, fixture inference and voice attachment lifecycle."""

import asyncio
import contextlib
import io
import os
import tempfile
import unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import patch

from me3.runtime import _console


class Worker:
    async def run(self, *args, **kwargs):
        return "saved result"


class ConsoleOutput(io.StringIO):
    def __init__(self):
        super().__init__()
        self.events = {}

    def event(self, text):
        return self.events.setdefault(text, asyncio.Event())

    def write(self, text):
        result = super().write(text)
        for marker, event in self.events.items():
            if marker in text:
                event.set()
        return result


class ConsoleReportingTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, *, voice=False):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.output = ConsoleOutput()
        self.ready = self.output.event("ME3 runtime:")
        self.offer = self.output.event("By the way")
        self.queued = self.output.event("I have queued")
        stack.enter_context(contextlib.redirect_stdout(self.output))
        input_fd, writer_fd = os.pipe()
        input_stream = stack.enter_context(os.fdopen(input_fd))
        self.writer = stack.enter_context(os.fdopen(writer_fd, "wb", buffering=0))
        stack.enter_context(patch("sys.stdin", input_stream))
        stack.enter_context(patch("me3.harnesses.configured_backend", return_value=Worker()))
        stack.enter_context(patch("me3.foreground.configured_foreground", return_value=Worker()))
        if voice:
            self.attached = asyncio.Event()
            self.detach = asyncio.Event()
            async def run_voice():
                self.attached.set()
                await self.detach.wait()
            async def stop_voice():
                self.detach.set()
            async def build(*args, **kwargs):
                return run_voice(), stop_voice
            stack.enter_context(patch("me3.duplex_voice.build", new=build))
            audio_module = SimpleNamespace(
                LocalAudioTransport=lambda params: object(),
                LocalAudioTransportParams=lambda **params: params,
            )
            stack.enter_context(patch.dict("sys.modules", {
                "pipecat.transports.local.audio": audio_module,
            }))
        state = stack.enter_context(tempfile.TemporaryDirectory())
        task = asyncio.create_task(_console(Namespace(state=state, owner="alice", voice=voice)))
        async def quit_console():
            self.writer.write(b"/quit\n")
            await asyncio.wait_for(task, 3)
        self.addAsyncCleanup(quit_console)
        await asyncio.wait_for(self.ready.wait(), 3)

    async def test_console_offers_result_while_waiting_for_input(self):
        await self.connect()
        self.writer.write(b"/task write a draft\n")
        await asyncio.wait_for(self.queued.wait(), 1)
        await asyncio.wait_for(self.offer.wait(), 2)
        self.assertEqual(self.output.getvalue().count("By the way"), 1)

    async def test_voice_owns_offers_until_detach_then_console_resumes(self):
        await self.connect(voice=True)
        await asyncio.wait_for(self.attached.wait(), 1)
        self.writer.write(b"/task write a draft\n")
        await asyncio.wait_for(self.queued.wait(), 1)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.offer.wait(), 1.05)
        self.detach.set()
        await asyncio.wait_for(self.offer.wait(), 2)
