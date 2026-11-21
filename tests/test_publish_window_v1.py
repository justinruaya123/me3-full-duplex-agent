"""Browser/PTY bridge regression; no provider or GitHub calls."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from integrations.voicechat import window


class PublicationResponseTests(unittest.TestCase):
    def test_only_first_boolean_for_pending_request_is_written(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            response = folder / 'publication-response.json'
            (folder / 'publication.json').write_text('{"id":"current"}')
            for decision in ({'id': 'old', 'approved': True},
                             {'id': 'current', 'approved': 'true'}):
                window.publication_response(folder, decision)
                self.assertFalse(response.exists())
            for approved in (False, True):
                window.publication_response(
                    folder, {'id': 'current', 'approved': approved})
            self.assertEqual(json.loads(response.read_text()),
                             {'id': 'current', 'approved': False})


class PublishWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_dialog_over_canvas_after_reconnect_and_exact_decision(self):
        from playwright.async_api import async_playwright

        with (TemporaryDirectory() as tmp,
              patch.object(window, 'open_window') as opened):
            folder = Path(tmp)
            argv = [sys.executable, '-c', 'import time; time.sleep(30)']
            with (folder / 'lock').open('w+') as lock:
                server = asyncio.create_task(window.serve(argv, folder, lock))
                try:
                    async with asyncio.timeout(5):
                        while not opened.called:
                            await asyncio.sleep(.02)
                    url = opened.call_args.args[0]
                    async with async_playwright() as p:
                        executable = (shutil.which('chromium') or
                                      shutil.which('google-chrome'))
                        browser = await p.chromium.launch(
                            executable_path=executable)
                        try:
                            page = await browser.new_page()
                            await self.exercise_dialog(page, url, folder)
                        finally:
                            await browser.close()
                finally:
                    server.cancel()
                    await asyncio.gather(server, return_exceptions=True)
                    # serve installs signal handlers in the current event loop.
                    for sig in (window.signal.SIGINT, window.signal.SIGTERM):
                        asyncio.get_running_loop().remove_signal_handler(sig)

    async def exercise_dialog(self, page, url, folder):
        await page.goto(url)
        await page.locator('#duplex:enabled').wait_for(timeout=5000)
        await page.locator('#inspect').click()
        await page.locator('#canvas').click()
        prompt = folder / 'publication.json'
        response = folder / 'publication-response.json'
        decision = {'id': 'a' * 36, 'title': 'Publish to GitHub Pages?',
                    'detail': 'Revision 2 to github.com/octo/harbor\nindex.html'}

        def update(payload):
            temp = prompt.with_suffix('.tmp')
            temp.write_text(json.dumps(payload))
            temp.replace(prompt)

        update(decision)
        modal = page.get_by_role('dialog', name=decision['title'])
        await modal.wait_for(timeout=2000)
        self.assertEqual(await modal.locator('pre').inner_text(), decision['detail'])
        self.assertEqual(
            await page.locator('body').get_attribute('data-view'), 'canvas')
        cancel = modal.get_by_role('button', name='Cancel')
        self.assertTrue(await cancel.evaluate(
            'node => node === document.activeElement'))
        await page.reload()
        await modal.wait_for(timeout=5000)
        await page.keyboard.press('Escape')
        async with asyncio.timeout(2):
            while not response.exists():
                await asyncio.sleep(.02)
        self.assertEqual(json.loads(response.read_text()),
                         {'id': decision['id'], 'approved': False})
        update(None)
        await modal.wait_for(state='hidden', timeout=2000)
        response.unlink()
        decision['id'] = 'b' * 36
        update(decision)
        await modal.wait_for(timeout=2000)
        await modal.get_by_role('button', name='Publish').click()
        async with asyncio.timeout(2):
            while not response.exists():
                await asyncio.sleep(.02)
        self.assertEqual(json.loads(response.read_text()),
                         {'id': decision['id'], 'approved': True})
        update(None)
        await modal.wait_for(state='hidden', timeout=2000)
