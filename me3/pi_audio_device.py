"""Mac full-duplex device, AEC reference, bounded speaker buffer and Pi stdio events."""

import asyncio
import base64
import json
import os
import queue
import threading
import time

RATE, FRAMES = 24000, 1920


def emit(kind, **fields):
    if os.environ.get("ME3_FDBENCH_URL") and kind in ("onset", "commit", "playing"):
        from fdbench_marks import mark
        if kind == "commit":
            mark("vad_end", t=fields["vad_end"])
            mark("asr_final", t=fields["final_at"], text=fields["text"])
        elif kind == "playing":
            mark("audio_out", t=fields["first_output"])
        else:
            mark("vad_start")
    print(json.dumps({"kind": kind, **fields}), flush=True)


class Devices:
    def __init__(self, *, frames=FRAMES, queue_frames=8, input_index=None, output_index=None):
        import pyaudio
        import numpy as np
        from pywebrtc_audio import AudioProcessor

        self.np = np
        self.aec = AudioProcessor(sample_rate=RATE, num_channels=1, echo_cancellation=True,
                                  noise_suppression=True, stream_delay_ms=int(
                                      os.environ.get("VOICECHAT_ECHO_DELAY_MS", "80")))
        self.pa = pyaudio.PyAudio()
        self.mic = queue.Queue(maxsize=queue_frames)
        self.paused = False
        self.playing = bytearray()
        self.listening_cue = bytearray()
        self.lock = threading.Lock()
        self.overrun = False
        self.delivered = 0
        self.first_reply_signal = None
        self.pause_requested = False
        self.pause_callback = None
        self.signal_frames = 0
        self.last_audible = self.capture_time = 0.

        def callback(data, count, timing, flags):
            timestamp = time.monotonic()
            size = count * 2
            with self.lock:
                if self.pause_requested and self.paused:
                    self.pause_callback = timestamp
                    self.pause_requested = False
                source = self.listening_cue if self.paused else self.playing
                out = source[:size]
                del source[:len(out)]
                self.delivered += len(out)
                if out and max(memoryview(out).cast("h")) > 64:
                    self.signal_frames += len(out) // 2
                    self.last_audible = timestamp
                    if source is self.playing and self.first_reply_signal is None:
                        self.first_reply_signal = timestamp
            reference = bytes(out).ljust(size, b"\0")
            try:
                self.mic.put_nowait((data, reference, timestamp))
            except queue.Full:
                self.overrun = True
            return reference, pyaudio.paContinue

        try:
            self.stream = self.pa.open(format=pyaudio.paInt16, channels=1,
                                       rate=RATE, input=True, output=True,
                                       input_device_index=input_index, output_device_index=output_index,
                                       frames_per_buffer=frames, stream_callback=callback)
        except BaseException:
            self.pa.terminate()
            raise

    def capture(self):
        near, reference, self.capture_time = self.mic.get_nowait()
        return self.aec.process(self.np.frombuffer(near, dtype="<i2"),
                                self.np.frombuffer(reference, dtype="<i2")).tobytes()

    def clear(self):
        with self.lock:
            self.playing.clear()
            if hasattr(self, "listening_cue"):
                self.listening_cue.clear()

    def native_audio(self, encoded):
        # Never wait on speaker capacity inside the socket reader: it must also
        # receive speech_started so barge-in can flush buffered PCM immediately.
        if not isinstance(encoded, str) or not 0 < len(encoded) <= 256000:
            raise ValueError("Invalid Nemotron audio delta")
        pcm = base64.b64decode(encoded, validate=True)
        if not pcm or len(pcm) % 2:
            raise ValueError("Nemotron audio requires whole PCM16 samples")
        with self.lock:
            if len(self.playing) + len(pcm) > 4 * RATE * 2:
                raise BufferError("Nemotron playback exceeds four seconds of buffered audio")
            self.playing.extend(pcm)

    async def enqueue(self, pcm):
        while True:
            with self.lock:
                if len(self.playing) <= FRAMES * 4:
                    self.playing.extend(pcm)
                    return
            await asyncio.sleep(.01)

    def close(self):
        self.clear()
        self.stream.close()
        self.pa.terminate()
