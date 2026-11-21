"""Owner profile, scoped recall, and generated site acceptance regressions."""

import asyncio
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from me3.memory import MemoryStore, SessionMemory
from me3.website import REQUEST_PREFIX, WebsiteWorker, prepare_website
from test_website_v1 import HTML, bundle


class Jobs:
    session_id = "session-one"
    owner = "alice"


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root / "memory.sqlite3")
        self.addCleanup(self.store.close)
        self.session = SessionMemory(
            self.store, Jobs(), lambda: True, lambda *args: None
        )

    def test_publication_requires_explicit_section_and_private_atomic_file(self):
        from me3.memory import worker_clarification

        command = self.session.command
        command("/project orchid = private project")
        command("/profile private tea = private preference")
        request = REQUEST_PREFIX + "about me"
        self.assertTrue(worker_clarification(self.session, request))
        command("/profile public bio = I design ceramics.")
        path = self.root / "owners/alice/USER.md"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertIn("Public-approved bio", path.read_text())
        self.assertIn("version: 2", path.read_text())
        snapshot = self.store.context("alice", request, worker=True)
        self.assertIn("I design ceramics.", snapshot)
        self.assertNotIn("private", snapshot)
        self.assertIsNone(worker_clarification(self.session, request))
        self.assertNotIn("ceramics", self.store.context("bob", request))
        command("/profile forget public bio")
        self.assertTrue(worker_clarification(self.session, request))
        self.assertNotIn("ceramics", path.read_text())
        command("/memory clear")
        self.assertFalse(path.exists())

    def test_personal_request_cannot_forward_freeform_private_bio(self):
        from me3.memory import worker_clarification

        self.session.command("/profile public name = Jordan Alder")
        question = worker_clarification(
            self.session, REQUEST_PREFIX + "about me. I live at 54 High Street"
        )
        self.assertIn("approve", question.lower())
        self.assertIsNone(
            worker_clarification(
                self.session, REQUEST_PREFIX + "about me with a blue theme"
            )
        )

    def test_ambiguous_alias_versions_scope_and_history(self):
        from me3.memory import worker_clarification

        cmd = self.session.command
        cmd("/alias project/iris gem = Iris prototype")
        cmd("/alias project/orchid gem = Orchid prototype")
        cmd("/decision project/iris color = amber")
        cmd("/decision project/iris color = indigo")
        self.assertIn("project/iris", worker_clarification(self.session, "design gem"))
        self.assertIsNone(worker_clarification(self.session, "project/iris design gem"))
        snapshot = self.store.context("alice", "project/iris gem", worker=True)
        self.assertIn("Iris prototype", snapshot)
        self.assertIn("indigo", snapshot)
        self.assertNotIn("amber", snapshot)
        self.assertNotIn("Orchid prototype", snapshot)
        history = cmd("/history project/iris color")
        self.assertIn("amber", history)
        self.assertIn("indigo", history)
        self.assertIn("superseded", history)
        self.assertNotIn("indigo", self.store.context("bob", "project/iris gem"))
        cmd("/forget project/iris color")
        self.assertNotIn("amber", cmd("/history project/iris color"))

    def test_owner_scoped_vocabulary_and_failed_save(self):
        cmd = self.session.command
        cmd("/profile vocabulary iris = Van Gogh")
        self.assertEqual(self.session.vocabulary("discuss iris"), ("Van Gogh",))
        self.assertFalse(self.session.vocabulary("tell me about Jupiter"))
        with patch("me3.memory.os.replace", side_effect=OSError("private path")):
            with self.assertRaisesRegex(RuntimeError, "memory storage"):
                cmd("/profile vocabulary iris = Changed")
        self.assertEqual(self.session.vocabulary("discuss iris"), ("Van Gogh",))
        cmd("/memory off")
        self.assertFalse(self.session.vocabulary("discuss iris"))


class BrowserAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_javascript_layout_and_link_errors_reject_the_site(self):
        for insertion in (
            '<a href="#absent">More</a>',
            '<a href="#details" onclick="return false">More</a><p id="details">Text</p>',
            '<script>console.error("bad")</script>',
            '<div style="width:5000px">Wide</div>',
            '<img src="https://example.invalid/never">',
        ):
            with (
                self.subTest(insertion=insertion),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                with self.assertRaisesRegex(ValueError, "browser"):
                    await prepare_website(
                        bundle(
                            {
                                "index.html": HTML.replace(
                                    "</body>", insertion + "</body>"
                                ),
                                "app.js": "void 0;",
                            }
                        ),
                        root,
                        lambda: True,
                    )
                self.assertFalse((root / "site").exists())

    async def test_real_browser_receipt_and_bio_content_checked(self):
        class Backend:
            async def run(inner, prompt, workspace):
                return bundle().split("\n", 1)[1]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "job-id/revision-2"
            root.mkdir(parents=True)
            store = MemoryStore(root.parent.parent / "memory.sqlite3")
            self.addCleanup(store.close)
            session = SessionMemory(store, Jobs(), lambda: True, lambda *args: None)
            session.command("/profile public name = Jordan Alder")
            worker = WebsiteWorker(
                Backend(),
                memory_context=lambda p, w: store.context("alice", p, worker=True),
            )
            output = await worker.run(REQUEST_PREFIX + "about me", root)
            with self.assertRaisesRegex(ValueError, "approved content"):
                await prepare_website(output, root, lambda: True)

            class InventedBiography:
                async def run(self, prompt, workspace):
                    html = HTML.replace(
                        "<h1>Site</h1>",
                        "<h1>Jordan Alder</h1><p>Winner of a Nobel prize.</p>",
                    )
                    return bundle({"index.html": html, "app.js": "void 0;"}).split(
                        "\n", 1
                    )[1]

            worker.backend = InventedBiography()
            output = await worker.run(REQUEST_PREFIX + "about me", root)
            with self.assertRaisesRegex(ValueError, "unapproved"):
                await prepare_website(output, root, lambda: True)
            await prepare_website(bundle(), root, lambda: True)
            receipt = json.loads((root / "verification.json").read_text())
            self.assertEqual(receipt["revision"], 2)
            self.assertEqual(receipt["job_id"], "job-id")
            self.assertEqual(
                set(receipt["browser"]["viewports"]), {"desktop", "mobile"}
            )


class RevisionBriefTests(unittest.IsolatedAsyncioTestCase):
    async def test_revise_build_in_flight_keeps_goal_and_ordered_changes(self):
        from me3.runtime import AgentRuntime
        from unittest.mock import AsyncMock

        class Worker:
            def __init__(self):
                self.prompts = asyncio.Queue()
                self.release = asyncio.Event()

            async def run(self, prompt, workspace):
                await self.prompts.put(prompt)
                await self.release.wait()

        with tempfile.TemporaryDirectory() as directory:
            worker = Worker()
            runtime = AgentRuntime(Path(directory), worker, object())
            session = runtime.open_session(AsyncMock(), AsyncMock(), owner="alice")
            try:
                job = session.jobs.submit(
                    REQUEST_PREFIX + "bakery menu with weekend hours"
                )
                await asyncio.wait_for(worker.prompts.get(), 1)
                session.jobs.revise(job["id"], "make it blue", expected_revision=1)
                second = await asyncio.wait_for(worker.prompts.get(), 1)
                self.assertIn("bakery menu with weekend hours", second)
                self.assertIn("make it blue", second)
                session.jobs.revise(
                    job["id"], "move the hours to the top", expected_revision=2
                )
                third = await asyncio.wait_for(worker.prompts.get(), 1)
                for term in (
                    "bakery menu",
                    "make it blue",
                    "move the hours to the top",
                ):
                    self.assertIn(term, third)
            finally:
                await runtime.close()

    async def test_revised_personal_goal_discards_revoked_old_bio(self):
        from me3.runtime import AgentRuntime
        from unittest.mock import AsyncMock

        class Worker:
            def __init__(self):
                self.prompts = asyncio.Queue()

            async def run(self, prompt, workspace):
                await self.prompts.put(prompt)
                await asyncio.Event().wait()

        with tempfile.TemporaryDirectory() as directory:
            worker = Worker()
            runtime = AgentRuntime(
                Path(directory), worker, object(), memory_enabled=True
            )
            session = runtime.open_session(AsyncMock(), AsyncMock(), owner="alice")
            try:
                session.memory.command("/profile public bio = I make ceramics")
                session.memory.command("/profile public name = Alice Gold")
                job = session.jobs.submit(
                    REQUEST_PREFIX + "about me I make ceramics with a dark theme"
                )
                await asyncio.wait_for(worker.prompts.get(), 1)
                session.memory.command("/profile forget public bio")
                fenced = session.jobs.get(job["id"])
                self.assertEqual(fenced["status"], "interrupted")
                with self.assertRaisesRegex(ValueError, "public email"):
                    session.jobs.revise(
                        job["id"],
                        "include my email",
                        expected_revision=fenced["revision"],
                    )
                session.jobs.revise(
                    job["id"], "make it blue", expected_revision=fenced["revision"]
                )
                prompt = await asyncio.wait_for(worker.prompts.get(), 1)
                self.assertNotIn("ceramics", prompt)
                for term in ("Alice Gold", "dark", "blue"):
                    self.assertIn(term, prompt)
            finally:
                await runtime.close()

    async def test_only_verified_ordinary_files_can_supply_revision_context(self):
        import hashlib
        from unittest.mock import AsyncMock

        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "bakery-job"
            previous = job / "revision-1"
            workspace = job / "revision-2"
            workspace.mkdir(parents=True)
            site = previous / "site"
            site.mkdir(parents=True)
            files = {
                "index.html": "<p>Wholegrain</p>",
                "app.css": ":root{--accent:cobalt}",
            }
            hashes = {}
            for name, value in files.items():
                (site / name).write_text(value)
                hashes[name] = hashlib.sha256(value.encode()).hexdigest()
            receipt = {
                "passed": True,
                "kind": "trusted-static-build",
                "job_id": job.name,
                "revision": 1,
                "reusable_source": True,
                "sha256": hashes,
                "browser": {"viewports": ["mobile", "desktop"]},
            }
            path = previous / "verification.json"
            path.write_text(json.dumps(receipt))
            backend = AsyncMock()
            backend.run.return_value = bundle().split("\n", 1)[1]
            worker = WebsiteWorker(backend)
            await worker.run(REQUEST_PREFIX + "bakery\nOwner change:\nblue", workspace)
            self.assertIn("--accent:cobalt", backend.run.await_args.args[0])
            (site / "app.css").write_text("unverified")
            with self.assertRaisesRegex(ValueError, "changed"):
                await worker.run(REQUEST_PREFIX + "bakery revised", workspace)
            receipt["reusable_source"] = False
            path.write_text(json.dumps(receipt))
            await worker.run(REQUEST_PREFIX + "bakery revised", workspace)
            self.assertNotIn("unverified", backend.run.await_args.args[0])
