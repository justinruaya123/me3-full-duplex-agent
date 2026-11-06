# Source review

The independent reviewer inspected commits87c3336 and03e1ff7, including the
installed Whisper call paths. No remaining Important or Critical findings.

Encoder reuse is confined to one serialized native request, keys exact mel
shape/dtype/bytes, restores the encoder, and clears retained input/features.
Capture reuse requires identical full PCM and generation, clears on lifecycle
invalidation, and final commitment still requires SmartTurn and stale checks.

Source inspection only: the reviewer ran no tests, models, providers, GPU,
microphone or benchmark calls. Native/HTTP/benchmark performance evidence is
reported separately.
