import tempfile
import unittest
from pathlib import Path


class BmoCacheTests(unittest.TestCase):
    def test_only_changed_or_damaged_phrases_render_again(self):
        from me3.bmo import build_cache, read_clip
        calls = []
        def render(text):
            calls.append(text)
            return b"\x01\x00" * 480
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            build_cache(cache, ["Hey.", "On it."], render)
            build_cache(cache, ["Hey.", "I'm here."], render)
            self.assertEqual(calls, ["Hey.", "On it.", "I'm here."])
            self.assertEqual(len(read_clip(cache, "Hey.")), 960)
            next(cache.glob("*.wav")).write_bytes(b"broken")
            build_cache(cache, ["Hey.", "On it.", "I'm here."], render)
            self.assertEqual(len(calls), 4)

    def test_failed_render_never_publishes_clip(self):
        from me3.bmo import build_cache
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with self.assertRaisesRegex(ValueError, "On it"):
                build_cache(cache, ["On it."], lambda _: b"")
            self.assertFalse(list(cache.glob("*.wav")))


class BmoPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_clip_uses_device_and_does_not_load_synthesizer(self):
        from threading import Lock
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock, patch
        from me3.parakeet_voice import Playback

        playback = Playback.__new__(Playback)
        device = SimpleNamespace(lock=Lock(), delivered=0, signal_frames=0, playing=False)
        async def enqueue(pcm):
            device.delivered += len(pcm)
            device.signal_frames += len(pcm) // 2
            device.first_reply_signal = 10.
        device.enqueue = AsyncMock(side_effect=enqueue)
        playback.device = device
        playback.listener_receipt = None
        playback.clips = {"Hey.": bytes.fromhex("0800") * 3000}
        playback.engine = Mock()
        with patch("me3.parakeet_voice.emit") as emit:
            await playback.speak("Hey.", receipt="wake", cached=True)
        playback.engine.synthesize.assert_not_called()
        self.assertEqual(device.enqueue.await_count, 2)
        self.assertEqual(emit.call_args.kwargs["receipt"], "wake")
        self.assertEqual(emit.call_args.kwargs["signal_frames"], 3000)

    def test_resuming_midcue_discards_unheard_tail_and_never_confirms_it(self):
        from threading import Lock
        from types import SimpleNamespace
        from unittest.mock import patch
        from me3.parakeet_voice import Playback

        playback = Playback.__new__(Playback)
        playback.device = SimpleNamespace(lock=Lock(), listening_cue=bytearray(32), signal_frames=10)
        playback.listener_receipt = ("turn", "Mm-hm.", 0)
        with patch("me3.parakeet_voice.emit") as emit:
            playback.quiet_cue()
            playback.observe_listener()
            emit.assert_not_called()
            self.assertFalse(playback.device.listening_cue)
            playback.listener_receipt = ("next", "I'm listening.", 3)
            playback.observe_listener()
            emit.assert_called_once_with("listener_played", id="next", text="I'm listening.")
