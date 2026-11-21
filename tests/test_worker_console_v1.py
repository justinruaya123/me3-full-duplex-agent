import unittest

from me3.web_client.worker_console import WorkerDrafts


class WorkerDraftTests(unittest.TestCase):
    def test_reader_can_resume_or_recover_after_missing_output(self):
        drafts = WorkerDrafts(max_jobs=2, max_chars=12)
        drafts.append("job", 1, "First\n")
        prior = drafts.read("job", 1, 0)
        drafts.append("job", 1, "paragraph")
        self.assertEqual(drafts.read("job", 1, prior["end"])["text"], "paragraph")
        late = drafts.read("job", 1, 0)
        self.assertEqual(late, {"start": 3, "end": 15, "text": "st\nparagraph"})
        drafts.append("job", 2, "new")
        self.assertEqual(drafts.read("job", 2, 0)["text"], "new")
        drafts.append("another", 1, "other")
        self.assertIsNone(drafts.read("job", 1, 0))


class WorkerStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from unittest.mock import Mock
        from me3.web_client.worker_console import stream_output

        self.drafts = WorkerDrafts()
        self.jobs = Mock()
        self.jobs.get.return_value = {"revision": 2, "status": "completed"}
        app = web.Application()
        async def read(request):
            return await stream_output(request, self.jobs, self.drafts, lambda: False)
        app.router.add_get('/jobs/{id}/output', read)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def packet(self, revision, offset=0):
        import json
        response = await self.client.get(f'/jobs/example/output?revision={revision}',
                                         headers={'Last-Event-ID': str(offset)})
        self.assertEqual(response.status, 200)
        lines = (await response.text()).splitlines()
        return json.loads(next(line[6:] for line in lines if line.startswith("data: ")))

    async def test_resume_and_superseded_revision_never_mix_text(self):
        self.drafts.append("example", 1, "old")
        self.drafts.append("example", 2, "new\ntext")
        current = await self.packet(2, 3)
        self.assertEqual((current['text'], current['status']), ('\ntext', 'completed'))
        old = await self.packet(1)
        self.assertEqual((old['text'], old['status']), ('old', 'superseded'))

    async def test_saved_result_identified_and_unknown_job_rejected(self):
        self.jobs.result.return_value = "Stored report"
        saved = await self.packet(2)
        self.assertEqual((saved['source'], saved['text']), ('Saved result', 'Stored report'))
        self.jobs.result.assert_called_once_with('example', expected_revision=2)
        self.jobs.get.side_effect = KeyError()
        response = await self.client.get('/jobs/foreign/output?revision=2')
        self.assertEqual(response.status, 404)
