import unittest
from unittest.mock import AsyncMock, Mock
from me3.web_client.live import BrowserCapture


class BrowserCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_noise_never_reaches_whisper(self):
        vad = Mock(analyze_audio=AsyncMock(return_value=Mock(name="state")))
        vad.analyze_audio.return_value.name = "QUIET"
        recognize = AsyncMock(return_value="Thank you.")
        capture = BrowserCapture("session", vad, recognize, AsyncMock(), AsyncMock(),
                                 Mock(), Mock(), Mock())
        for _ in range(35):
            await capture.feed(b'\xff\x18' * 512)
        recognize.assert_not_awaited()
        self.assertFalse(capture.rolling.active)
        vad.cleanup = AsyncMock()
        await capture.close()
