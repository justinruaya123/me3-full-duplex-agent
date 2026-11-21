import asyncio
import tempfile
import unittest
from pathlib import Path

from me3.voicechat_site import build_site
from me3.voicechat_trial import decoder_capacity_error


class VoiceSiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_survives_duplicate_and_concurrent_requests(self):
        html = '<meta name="viewport" content="width=device-width"><h1>Test Harbor</h1>'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = await asyncio.gather(*[build_site(root, "my-turn", html) for _ in range(2)])
            self.assertEqual(a, b)
            self.assertEqual(Path(a["index"]).read_text(), html)
            self.assertTrue(Path(a["receipt"]).is_file())
            self.assertEqual(await build_site(root, "my-turn", "changed"), a)

    async def test_bad_site_never_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "viewport"):
                await build_site(Path(tmp), "turn", "<h1>No viewport</h1>")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_download_requires_a_completed_job_in_the_current_window(self):
        import json
        from integrations.voicechat.window import website_download
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_id = "a" * 32
            archive = root / "chats" / "demo" / "jobs" / job_id / "revision-1" / "website.zip"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"fixture")
            job = {"id":job_id, "revision":1, "kind":"website", "status":"completed", "archive":str(archive)}
            name = f"website-{job_id}-1.zip"
            for record, expected in [(job, archive), (job | {"status":"failed"}, None),
                                     (job | {"revision":2}, None), (job | {"archive":str(root)}, None)]:
                (root / "agents.json").write_text(json.dumps([record]))
                self.assertEqual(website_download(name, root, root / "chats"), expected)

    def test_only_specific_decoder_capacity_failure_is_retryable(self):
        error = {"code":"inference_error", "message":"LLMBackbone: llama_decode (batched step) failed with code 1"}
        self.assertTrue(decoder_capacity_error(error))
        self.assertFalse(decoder_capacity_error(error | {"message":error["message"]+"0"}))
        self.assertFalse(decoder_capacity_error(error | {"code":"permission_error"}))
        self.assertFalse(decoder_capacity_error("error"))
