"""Host-owned website effects: generated output never selects commands."""

import json
import tempfile
import unittest
from pathlib import Path

HTML = (
    '<!doctype html><html><head><meta name="viewport" '
    'content="width=device-width,initial-scale=1"></head>'
    '<body><h1>Site</h1><script src="app.js"></script></body></html>'
)


def bundle(files=None):
    return "ME3_WEBSITE_BUNDLE\n" + json.dumps(
        {
            "files": files
            or {
                "index.html": HTML,
                "app.js": 'document.title = "Site";',
                "style.css": "body {max-width: 60rem; margin: auto;}",
            }
        }
    )


class WebsiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_writes_files_and_records_real_syntax_receipt(self):
        from me3.website import prepare_website

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = await prepare_website(bundle(), root, lambda: True)
            self.assertTrue((root / "site/index.html").is_file())
            receipt = json.loads((root / "verification.json").read_text())
            self.assertTrue(receipt["passed"])
            self.assertIn("node --check", receipt["checks"])
            self.assertIn("index.html", receipt["sha256"])
            self.assertIn("verified", result.lower())

    async def test_fenced_pi_output_exports_only_the_verified_site(self):
        from zipfile import ZipFile
        from me3.website import BUNDLE_PREFIX, prepare_website
        raw = bundle().removeprefix(BUNDLE_PREFIX)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker-preview.txt").write_text("Private worker state")
            await prepare_website(BUNDLE_PREFIX + "```json\n" + raw + "\n```", root, lambda: True)
            with ZipFile(root / "website.zip") as archive:
                self.assertEqual(set(archive.namelist()), {"index.html", "style.css", "app.js", ".nojekyll"})
                self.assertEqual(archive.read("index.html").decode(), HTML)

    def test_generated_pages_readme_and_empty_nojekyll_marker_are_accepted(self):
        from me3.website import checked_files
        files = {"index.html": HTML, "README.md": "Upload instructions", ".nojekyll": ""}
        self.assertEqual(checked_files(json.dumps({"files": files})),
                         {"index.html": HTML, "README.md": "Upload instructions"})

    def test_only_one_complete_json_response_is_accepted(self):
        from me3.website import checked_files
        raw = bundle().split("\n", 1)[1]
        for text in ("Here it is: " + raw, "```json\n" + raw, raw + "\n" + raw):
            with self.subTest(text=text[:10]), self.assertRaisesRegex(ValueError, "complete JSON"):
                checked_files(text)

    async def test_worker_can_recover_once_from_an_incomplete_reply(self):
        from unittest.mock import AsyncMock
        from me3.website import WebsiteWorker, REQUEST_PREFIX

        backend = AsyncMock()
        backend.run.side_effect = ["Here is the page:", bundle().split("\n", 1)[1]]
        with tempfile.TemporaryDirectory() as directory:
            output = await WebsiteWorker(backend).run(REQUEST_PREFIX + "Build a small page", Path(directory))
        self.assertEqual(output, bundle())
        self.assertEqual(backend.run.await_count, 2)

    async def test_stale_result_cannot_write_files_or_run_build(self):
        from me3.website import prepare_website

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Stale"):
                await prepare_website(bundle(), root, lambda: False)
            self.assertFalse(list(root.iterdir()))

    async def test_path_escape_symlinks_and_package_scripts_are_rejected(self):
        from me3.website import prepare_website

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "../escape.js",
                "/tmp/escape.js",
                ".git/config",
                "a/../../escape.js",
                "a\\escape.js",
                "package.json",
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    await prepare_website(
                        bundle({"index.html": HTML, name: "bad"}),
                        root,
                        lambda: True,
                    )
            (root / "site").symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                await prepare_website(bundle(), root, lambda: True)

    async def test_invalid_javascript_and_missing_viewport_never_pass(self):
        from me3.website import prepare_website

        for files in (
            {"index.html": HTML, "app.js": "const = broken;"},
            {"index.html": "<html><body>missing viewport</body></html>"},
        ):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    await prepare_website(
                        bundle(files), Path(directory), lambda: True
                    )
                self.assertFalse(
                    (Path(directory) / "verification.json").exists()
                )

    async def test_oversized_bundle_and_inline_syntax_errors_are_rejected(
        self,
    ):
        from me3.website import prepare_website

        for files in (
            {"index.html": HTML + "x" * 1_100_000},
            {
                "index.html": HTML.replace(
                    "</body>", "<script>const = broken</script></body>"
                )
            },
        ):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    await prepare_website(
                        bundle(files), Path(directory), lambda: True
                    )


class PiWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_rpc_reuses_job_process_and_checks_exact_model(
        self,
    ):
        import sys

        from me3.pi_worker import PersistentPiBackend

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "worker.py"
            child.write_text("""import json,sys,os
count=0
for line in sys.stdin:
 r=json.loads(line)
 if r['type']=='get_state':
  data={'model':{'id':'exact','provider':'provider'}}
 elif r['type']=='prompt':
  count+=1
  print(json.dumps({'type':'response','id':r['id'],'success':True}),flush=True)
  print(json.dumps({'type':'message_end','message':{'role':'assistant','stopReason':'stop'}}),flush=True)
  print(json.dumps({'type':'agent_settled'}),flush=True)
  continue
 else:
  data={'text':str(os.getpid())+':'+str(count)}
 print(json.dumps({'type':'response','id':r['id'],'success':True,'data':data}),flush=True)
""")
            backend = PersistentPiBackend(
                (sys.executable, str(child)),
                model="exact",
                provider="provider",
            )
            try:
                a = await backend.run("first", root / "job/revision-1")
                b = await backend.run("correction", root / "job/revision-2")
                self.assertEqual(a.split(":")[0], b.split(":")[0])
                self.assertTrue(b.endswith(":2"))
            finally:
                await backend.close()

    async def test_wrong_model_is_rejected_before_prompt(self):
        import sys

        from me3.pi_worker import PersistentPiBackend

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "prompted"
            child = root / "worker.py"
            child.write_text(
                "import json,sys,pathlib\n"
                "for line in sys.stdin:\n"
                " r=json.loads(line)\n"
                f' if r["type"]=="prompt": pathlib.Path({str(marker)!r}).touch()\n'
                ' print(json.dumps({"type":"response","id":r["id"],'
                '"success":True,"data":{"model":{"id":"wrong",'
                '"provider":"provider"}}}),flush=True)\n'
            )
            backend = PersistentPiBackend(
                (sys.executable, str(child)),
                model="exact",
                provider="provider",
            )
            try:
                with self.assertRaisesRegex(ValueError, "model"):
                    await backend.run("must not run", root / "job/revision-1")
                self.assertFalse(marker.exists())
            finally:
                await backend.close()
