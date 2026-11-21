import asyncio
import tempfile
import unittest
from pathlib import Path

from me3.voicechat_jobs import VoiceJobs


class VoiceJobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_submitted_work_is_independent_and_survives_reopening(self):
        ready = asyncio.Event()
        events = []

        class Worker:
            async def run(self, prompt, workspace, *, foreground=False):
                await ready.wait()
                return "The completed draft"

        with tempfile.TemporaryDirectory() as folder:
            jobs = VoiceJobs(Path(folder), Worker(), events.append)
            try:
                job = jobs.submit("draft", "Write a plan", "turn-id")
                self.assertEqual(job["status"], "queued")
                self.assertEqual(jobs.submit("draft", "Write a plan", "turn-id")["id"], job["id"])
                ready.set()
                await jobs.supervisor.wait(job["id"])
                self.assertEqual(jobs.status(job["id"])["text"], "The completed draft")
            finally:
                await jobs.close()
            again = VoiceJobs(Path(folder), Worker(), events.append)
            try:
                self.assertEqual(again.status(job["id"])["status"], "completed")
            finally:
                await again.close()

    async def test_follow_up_is_revision_scoped_and_acknowledged_after_playback(self):
        class Worker:
            async def run(self, *args, **kwargs):
                return "The review is Thursday."
        with tempfile.TemporaryDirectory() as folder:
            jobs = VoiceJobs(Path(folder), Worker(), lambda _: None)
            try:
                job = jobs.submit("draft", "Write an agenda", "one", follow_up=True)
                self.assertTrue(job["follow_up"])
                self.assertTrue(jobs.claim_cue(job["id"], job["revision"]))
                self.assertFalse(jobs.claim_cue(job["id"], job["revision"]))
                self.assertEqual(jobs.notices(), [])
                await jobs.supervisor.wait(job["id"])
                self.assertEqual(jobs.notices()[0]["text"], "The review is Thursday.")
                with self.assertRaises(ValueError):
                    jobs.jobs.acknowledge(job["id"], job["revision"] + 1)
                jobs.jobs.acknowledge(job["id"], job["revision"])
                self.assertEqual(jobs.notices(), [])
            finally:
                await jobs.close()

    async def test_draft_cannot_submit_a_website_by_embedding_its_internal_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            jobs = VoiceJobs(Path(folder), object(), lambda _: None)
            try:
                with self.assertRaises(ValueError):
                    jobs.submit("draft", "  ME3_WEBSITE_REQUEST\nmake a site", "turn")
                self.assertEqual(jobs.status(), {"status": "empty"})
            finally:
                await jobs.close()

    async def test_website_worker_stream_is_visible_during_build(self):
        written = asyncio.Event()
        finish = asyncio.Event()

        class Worker:
            async def run(self, prompt, workspace, *, foreground=False):
                (workspace / "worker-preview.txt").write_text("drafted header")
                written.set()
                await finish.wait()
                return "{}"

        with tempfile.TemporaryDirectory() as folder:
            jobs = VoiceJobs(Path(folder), object(), lambda _: None, site_backend=Worker())
            try:
                job = jobs.submit("website", "Make a local page", "voice-turn")
                self.assertEqual(jobs.submit("website", "Make a local page", "voice-turn")["id"], job["id"])
                await asyncio.wait_for(written.wait(), 3)
                self.assertNotIn("preview", jobs.status(job["id"]))
                self.assertEqual(jobs.status(job["id"], for_display=True)["preview"],
                                 "drafted header")
            finally:
                finish.set()
                await jobs.close()

    async def test_approved_portfolio_archive_contains_only_selected_facts(self):
        import json
        import zipfile

        facts = [{"text": "Built the bridge <prototype>.", "url":"https://example.org/bridge"}]
        with tempfile.TemporaryDirectory() as folder:
            jobs = VoiceJobs(Path(folder), object(), lambda _: None)
            try:
                spec = json.dumps({"name":"Ada & Co", "facts":facts})
                job = jobs.submit("portfolio", spec, "approved")
                self.assertEqual(jobs.submit("portfolio", spec, "approved")["id"], job["id"])
                await jobs.supervisor.wait(job["id"])
                with zipfile.ZipFile(jobs.status(job["id"])["archive"]) as archive:
                    page = archive.read("index.html").decode()
                    self.assertIn("Ada &amp; Co", page)
                    self.assertIn("Built the bridge &lt;prototype&gt;.", page)
                    self.assertIn("https://example.org/bridge", page)
                    self.assertIn(".nojekyll", archive.namelist())
            finally:
                await jobs.close()
