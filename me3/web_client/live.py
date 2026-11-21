"""Continuous browser PCM, using the same bounded capture and VAD as normal voice."""

import asyncio
from dataclasses import replace
import uuid

from me3.capture import RollingCapture


def make_vad():
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams

    vad = SileroVADAnalyzer(params=VADParams(
        confidence=0.7, start_secs=0.096, stop_secs=0.2, min_volume=0.5,
    ))
    vad.set_sample_rate(16000)
    return vad


class BrowserCapture:
    def __init__(self, session_id, vad, recognize, analyze, transcript, mark, dismiss, error):
        self.vad = vad
        self.transcript = transcript
        self.mark = mark
        self.dismiss = dismiss
        self.error = error
        self.prefix = uuid.uuid4().hex
        self.tasks = set()
        self.rolling = RollingCapture(session_id, recognize, analyze, self._revision,
                                      max_seconds=12, preroll_seconds=0.75, on_empty=lambda _: self.dismiss())

    @property
    def group(self):
        return f"{self.prefix}-{self.rolling.turn}"

    async def _revision(self, event, pcm):
        generation = self.rolling.generation
        result = await self.transcript(replace(event, turn_id=self.group))
        if result == "backchannel" and not event.committed:
            self.rolling.consume_backchannel(event, generation=generation)
        if event.committed or result == "backchannel":
            await self.mark("resolved", self.group)

    def _track(self, task):
        if task in self.tasks:
            return
        self.tasks.add(task)
        def done(finished):
            self.tasks.discard(finished)
            if not finished.cancelled() and (exc := finished.exception()):
                self.error(exc)
        task.add_done_callback(done)

    async def _finish(self, final, generation):
        await final
        r = self.rolling
        if r.closed or r.generation != generation or r.active or r.committed or r.rolling is None:
            # Empty recognition retires its generation. Release only if still idle.
            if r.rolling is None and not r.active and not r.closed:
                await self.mark("resolved", self.group)
            return
        # An unfinished thought can continue with the same samples and revision ID.
        await asyncio.sleep(2)
        if r.generation == generation and not r.active and not r.closed:
            r.discard_incomplete()
            self.dismiss()
            await self.mark("expired", self.group)

    async def feed(self, pcm):
        if len(pcm) != 1024:
            raise ValueError("Expected a 32 ms mono PCM16 frame")
        state = await self.vad.analyze_audio(pcm)
        r = self.rolling
        if state.name == "SPEAKING" and not r.active:
            r.begin()
            await self.mark("start", self.group)
        r.feed(pcm)
        if r._partial and not r._partial.done():
            self._track(r._partial)
        if state.name == "QUIET" and r.active:
            final = r.end_vad_segment()
            await self.mark("stop", self.group)
            self._track(asyncio.create_task(self._finish(final, r.generation)))

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await self.rolling.close()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.vad.cleanup()
