import json
from pathlib import Path
import tempfile
import unittest

from scripts import bmo_setup as setup


class PortableSetupTests(unittest.TestCase):
    def test_transfer_preserves_private_keys_and_creates_device_local_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old, new = root / 'old', root / 'new'
            for host in (old, new):
                host.mkdir()
                (host / '.env.bmo.example').write_text('ME3_MEMORY_ENABLED=1\n')
            (old / '.env').write_text('OPENROUTER_API_KEY=secret\nME3_FOREGROUND_MODEL=some/model\nME3_MIC_DEVICE_INDEX=9\n')
            (new / '.env').write_text('OPENROUTER_API_KEY=keep\n')
            prompts = old / '.local/voice-prompts'
            prompts.mkdir(parents=True)
            (prompts / 'USER.md').write_text('Preferred name: Test')
            archive = root / 'bmo-config.json'
            setup.export_config(old, archive)
            self.assertNotIn('secret', archive.read_text())
            self.assertNotIn('DEVICE_INDEX', archive.read_text())
            setup.import_config(new, archive)
            self.assertEqual((new / '.local/voice-prompts/USER.md').read_text(), 'Preferred name: Test')
            self.assertIn('OPENROUTER_API_KEY=keep', (new / '.env').read_text())
            self.assertIn('ME3_FOREGROUND_MODEL=some/model', (new / '.env').read_text())
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_invalid_bundle_cannot_write_files_or_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'data'
            for settings, prompts in [({'OPENROUTER_API_KEY':'bad'}, {}),
                                     ({}, {'../outside':'oops'})]:
                path.write_text(json.dumps(dict(version=1, settings=settings, prompts=prompts)))
                with self.assertRaises(ValueError):
                    setup.import_config(root, path)
                self.assertFalse((root / '.env').exists())
