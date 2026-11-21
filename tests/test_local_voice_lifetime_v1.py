"""Device lifetime across full-duplex mode changes; no audio hardware needed."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from me3.runtime import start_local_voice


class LocalVoiceLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_audio_device_after_session_and_failed_attach(self):
        runtime = SimpleNamespace(supervisor=SimpleNamespace(root="."))
        device = Mock()
        transport = SimpleNamespace(_pyaudio=device)
        local_audio = SimpleNamespace(
            LocalAudioTransport=lambda params: transport,
            LocalAudioTransportParams=dict,
        )
        with patch.dict("sys.modules", {"pipecat.transports.local.audio": local_audio}):
            with patch("me3.duplex_voice.build", new_callable=AsyncMock) as build:
                build.side_effect = ValueError("missing wake phrase")
                with self.assertRaisesRegex(ValueError, "wake phrase"):
                    await start_local_voice(runtime)
                device.terminate.assert_called_once()

                device.reset_mock()
                build.side_effect = None
                build.return_value = (asyncio.sleep(0), object())
                task, _ = await start_local_voice(runtime)
                device.terminate.assert_not_called()
                await task
                device.terminate.assert_called_once()
