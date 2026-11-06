"""Request-local encoder reuse must preserve changed inputs and cleanup."""

import unittest
from types import SimpleNamespace


class WhisperInferenceTests(unittest.TestCase):
    def test_exact_input_is_reused_but_changed_input_is_encoded(self):
        from me3.whisper_inference import request_encoder

        calls = []

        def encode(value):
            calls.append(bytes(value))
            return sum(value)

        model = SimpleNamespace(encoder=encode)
        with request_encoder(model, key=bytes):
            value = bytearray([1, 2])
            self.assertEqual(model.encoder(value), 3)
            self.assertEqual(model.encoder(bytearray([1, 2])), 3)
            value[1] = 4
            self.assertEqual(model.encoder(value), 5)
            self.assertEqual(model.encoder(bytearray([1, 2])), 3)
        # One-entry cache: the earlier input must be re-encoded after a change.
        self.assertEqual(calls, [b"\x01\x02", b"\x01\x04", b"\x01\x02"])
        self.assertIs(model.encoder, encode)

    def test_requests_do_not_share_audio_or_encoded_features(self):
        from me3.whisper_inference import request_encoder

        calls = []

        def encode(value):
            calls.append(value)
            return len(calls)

        model = SimpleNamespace(encoder=encode)
        with request_encoder(model, key=bytes):
            cached = model.encoder
            self.assertEqual(cached(b"audio"), 1)
            self.assertEqual(cached(b"audio"), 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            cached(b"audio")
        with request_encoder(model, key=bytes):
            self.assertEqual(model.encoder(b"audio"), 2)
        self.assertEqual(calls, [b"audio", b"audio"])

    def test_failure_restores_model_and_does_not_publish_failed_features(self):
        from me3.whisper_inference import request_encoder

        calls = []

        def encode(value):
            calls.append(value)
            if len(calls) == 1:
                raise ValueError("native failure")
            return 42

        model = SimpleNamespace(encoder=encode)
        with self.assertRaisesRegex(ValueError, "native failure"):
            with request_encoder(model, key=bytes):
                cached = model.encoder
                cached(b"audio")
        self.assertIs(model.encoder, encode)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            cached(b"audio")
        with request_encoder(model, key=bytes):
            self.assertEqual(model.encoder(b"audio"), 42)
        self.assertEqual(len(calls), 2)
