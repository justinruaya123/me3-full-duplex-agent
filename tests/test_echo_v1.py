"""Project-owned reference rate conversion, bounds and capture/reference pairing."""

import importlib.util
import struct
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("numpy") and importlib.util.find_spec("soxr"),
    "Optional audio DSP dependencies are not installed",
)
class EchoTests(unittest.TestCase):
    def test_played_reference_is_resampled_and_paired_with_capture(self):
        import numpy as np

        from me3.echo import EchoFrontEnd

        pairs = []

        class Processor:
            def process(self, near, far):
                pairs.append((near.copy(), far.copy()))
                return near

            def reset(self):
                pass

        front = EchoFrontEnd(processor=Processor())
        # 100ms at 24kHz; reference is generated once and consumed at 16kHz.
        front.played(struct.pack("<h", 1200) * 2400, 24000)
        near = struct.pack("<h", 500) * 1600
        self.assertEqual(front.capture(near), near)
        self.assertEqual(len(pairs[0][0]), 1600)
        self.assertEqual(len(pairs[0][1]), 1600)
        self.assertGreater(np.count_nonzero(pairs[0][1]), 0)
        front.capture(near)
        self.assertFalse(np.count_nonzero(pairs[-1][1]))

    def test_wrong_rates_and_reference_overflow_fail_explicitly(self):
        from me3.echo import EchoFrontEnd

        class Processor:
            def process(self, near, far):
                return near

            def reset(self):
                pass

        front = EchoFrontEnd(processor=Processor(), max_reference_seconds=0.1)
        with self.assertRaises(ValueError):
            front.played(bytes(960), 48000)
        with self.assertRaises(BufferError):
            front.played(bytes(48000), 24000)
