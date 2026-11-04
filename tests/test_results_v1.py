"""Durable owner isolation, revisioned results and explicit preview/focus."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from me3.runtime import AgentRuntime
from test_website_v1 import bundle


class Worker:
    async def run(self, prompt, workspace, *, foreground=False):
        return bundle().split('\n', 1)[1] if 'JSON object' in prompt else 'done'


class ResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = AgentRuntime(Path(self.temp.name), Worker(), Worker())
        self.spoken = []

        async def speak(text):
            self.spoken.append(text)
            return True

        async def stop():
            pass

        self.session = self.runtime.open_session(speak, stop, owner='alice',
                                                  quiet_seconds=0)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.temp.cleanup()

    async def settle(self):
        for _ in range(20):
            await asyncio.sleep(0)

    async def test_dedup_and_owner_filter_survive_session_end(self):
        from me3.jobs import OwnedJobs
        jobs = self.session.jobs
        a = jobs.submit('draft', request_id='turn-1')
        b = jobs.submit('draft', request_id='turn-1')
        self.assertEqual(a['id'], b['id'])
        await self.runtime.end_session(self.session)
        other = OwnedJobs(self.runtime.supervisor, 'bob', 'new')
        self.assertFalse(other.list())
        with self.assertRaises(KeyError):
            other.get(a['id'])
        alice = OwnedJobs(self.runtime.supervisor, 'alice', 'renewed')
        self.assertEqual(alice.get(a['id'])['owner'], 'alice')

    async def test_completed_website_can_be_revised_and_old_result_is_fenced(self):
        from me3.website import REQUEST_PREFIX
        jobs = self.session.jobs
        job = jobs.submit(REQUEST_PREFIX + 'build a site')
        await self.runtime.supervisor.wait(job['id'])
        self.assertEqual(jobs.get(job['id'])['status'], 'completed')
        jobs.revise(job['id'], 'make it blue', expected_revision=1)
        with self.assertRaises(ValueError):
            jobs.result(job['id'], expected_revision=1)
        with self.assertRaises(ValueError):
            jobs.cancel(job['id'], expected_revision=1)
        await self.runtime.supervisor.wait(job['id'])
        self.assertEqual(jobs.get(job['id'])['revision'], 2)

    async def test_result_retrieval_does_not_replace_focus_or_earlier_thread(self):
        job = self.session.jobs.submit('draft')
        await self.runtime.supervisor.wait(job['id'])
        self.session.history.append({'role': 'user', 'content': 'earlier topic'})
        await self.session.accept('/result ' + job['id'])
        await self.settle()
        self.assertIsNone(self.session.focus)
        self.assertTrue(any(m['content'] == 'earlier topic'
                            for m in self.session.history))
        self.assertIn('done', ' '.join(self.spoken))

    async def test_ambiguous_cancel_and_show_never_choose_a_job(self):
        a = self.session.jobs.submit('one')
        b = self.session.jobs.submit('two')
        await self.runtime.supervisor.wait(a['id'])
        await self.runtime.supervisor.wait(b['id'])
        self.assertEqual(await self.session.accept('cancel that'), 'clarify')
        self.assertEqual(await self.session.accept('show it'), 'clarify')
        self.assertEqual(self.session.jobs.get(a['id'])['status'], 'completed')

    async def test_preview_requires_current_verified_files_and_is_loopback(self):
        from me3.website import REQUEST_PREFIX
        jobs = self.session.jobs
        job = jobs.submit(REQUEST_PREFIX + 'site')
        await self.runtime.supervisor.wait(job['id'])
        url = await jobs.preview(job['id'], expected_revision=1)
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        self.assertEqual(parsed.hostname, '127.0.0.1')
        reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
        writer.write(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        self.assertIn(b'200 OK', response)
        self.assertIn(b'Content-Security-Policy:', response)
        self.assertIn(b'<h1>Site</h1>', response)
        jobs.revise(job['id'], 'blue', expected_revision=1)
        with self.assertRaises((ConnectionRefusedError, OSError)):
            await asyncio.open_connection(parsed.hostname, parsed.port)

    async def test_tampered_artifact_cannot_start_preview(self):
        from me3.website import REQUEST_PREFIX
        jobs = self.session.jobs
        job = jobs.submit(REQUEST_PREFIX + 'site')
        await self.runtime.supervisor.wait(job['id'])
        record = jobs.get(job['id'])
        root = self.runtime.supervisor.root / Path(record['artifact']).parent
        (root / 'site/index.html').write_text('tampered')
        with self.assertRaises(ValueError):
            await jobs.preview(job['id'], expected_revision=1)

    async def test_closed_session_cannot_authorize_more_actions(self):
        jobs = self.session.jobs
        await self.runtime.end_session(self.session)
        with self.assertRaises(PermissionError):
            jobs.submit('stale delegated request')

    async def test_several_completions_are_grouped_without_focus_change(self):
        a = self.session.jobs.submit('one')
        b = self.session.jobs.submit('two')
        await self.runtime.supervisor.wait(a['id'])
        await self.runtime.supervisor.wait(b['id'])
        self.assertTrue(self.session.poll())
        await self.settle()
        self.assertEqual(len(self.spoken), 1)
        self.assertIn('2 background tasks', self.spoken[0])
        self.assertEqual(self.session.jobs.get(a['id'])['notified'], 1)
        self.assertEqual(self.session.jobs.get(b['id'])['notified'], 1)
        self.assertIsNone(self.session.focus)
