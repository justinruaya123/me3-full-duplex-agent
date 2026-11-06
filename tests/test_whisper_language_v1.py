"""Automatic language must preserve uncertainty and never force English."""

import math
import unittest


class AutomaticLanguageTests(unittest.TestCase):
    def test_confident_detected_language_does_not_force_english_or_redetect(
        self,
    ):
        from me3.whisper_inference import automatic_language

        def redetect():
            self.fail("Confident detection must use its own language")

        self.assertEqual(
            automatic_language({"en": 0.01, "es": 0.99}, redetect), "es"
        )

    def test_uncertain_decode_input_uses_standard_language_detection(self):
        from me3.whisper_inference import automatic_language

        calls = []

        def redetect():
            calls.append(True)
            return {"en": 0.25, "sv": 0.35, "de": 0.4}

        self.assertEqual(
            automatic_language({"en": 0.4, "fr": 0.3, "sv": 0.3}, redetect),
            "de",
        )
        self.assertEqual(calls, [True])

    def test_detection_failure_is_explicit(self):
        from me3.whisper_inference import automatic_language

        def redetect():
            raise RuntimeError("Language inference failed")

        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            automatic_language({"en": 0.5, "tl": 0.5}, redetect)

    def test_malformed_probabilities_cannot_select_an_implicit_language(self):
        from me3.whisper_inference import automatic_language

        for values in (
            {}, {"en": math.nan}, {"en": math.inf}, {"en": -0.1},
            {"en": 1.1}, {"en": "unknown"}, {"": 1.0},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                automatic_language(values, lambda: {"en": 1.0})
        with self.assertRaises(ValueError):
            automatic_language({"en": 0.5, "tl": 0.5}, lambda: {})


if __name__ == "__main__":
    unittest.main()
