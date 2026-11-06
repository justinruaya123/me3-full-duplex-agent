"""Replay actual pipeline tests with installed pre-change VAD defaults.

This controlled ablation changes only constructor parameters in this process.
It returns the real installed CPU analyzer and does not edit production files.
"""

import runpy
import sys
import unittest
from unittest.mock import patch

from pipecat.audio.vad import silero
from pipecat.audio.vad.vad_analyzer import VADParams


original_analyzer = silero.SileroVADAnalyzer


def baseline_analyzer(*args, **kwargs):
    kwargs["params"] = VADParams()
    return original_analyzer(*args, **kwargs)


namespace = runpy.run_path("tests/test_vad_onset_v1.py")
suite = unittest.defaultTestLoader.loadTestsFromTestCase(
    namespace["VADOnsetTests"]
)
print("Controlled baseline replay: actual CPU analyzer with", VADParams())
with patch.object(silero, "SileroVADAnalyzer", baseline_analyzer):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
