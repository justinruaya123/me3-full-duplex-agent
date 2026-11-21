import unittest
from me3.configuration import ForegroundConfig


class VoiceCallTests(unittest.TestCase):
    def test_pi_chat_is_an_explicit_foreground_selection_without_http(self):
        config = ForegroundConfig.from_env(dict(ME3_FOREGROUND_PROFILE="pi-chat",
            ME3_FOREGROUND_PROVIDER="openai-codex", ME3_FOREGROUND_MODEL="model"))
        self.assertEqual((config.profile, config.model), ("pi-chat", "model"))
