"""Local filesystem checks for the Pi chat work folder."""
import os
from pathlib import Path
import tempfile
import unittest

from me3.session_folder import SessionFolder


class SessionFolderTests(unittest.TestCase):
    def test_folder_follows_pi_chat_and_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = SessionFolder(root, "operator", "chat-one")
            first.save("meeting notes.txt", "Meet at noon.")
            resumed = SessionFolder(root, "operator", "chat-one")
            self.assertEqual(resumed.names(), ["meeting notes.txt"])
            self.assertEqual(resumed.read("meeting notes.txt"), "Meet at noon.")
            for owner, chat in (("operator", "chat-two"), ("other", "chat-one")):
                self.assertEqual(SessionFolder(root, owner, chat).names(), [])
            with self.assertRaises(ValueError):
                resumed.save("meeting notes.txt", "replacement")
            self.assertEqual(first.read("meeting notes.txt"), "Meet at noon.")

    def test_links_special_files_and_paths_cannot_leave_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = SessionFolder(root, "operator", "chat")
            outside = root / "outside.txt"
            outside.write_text("private")
            (folder.path / "linked.txt").symlink_to(outside)
            os.link(outside, folder.path / "alias.txt")
            os.mkfifo(folder.path / "pipe")
            for name in ("../outside.txt", str(outside), "linked.txt", "alias.txt",
                         "pipe", ".hidden", "sub/file"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    folder.read(name)
            self.assertEqual(folder.names(), [])
            with self.assertRaises(ValueError):
                folder.save("../outside.txt", "replacement")
            self.assertEqual(outside.read_text(), "private")

    def test_model_can_create_only_the_named_file_on_an_explicit_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = SessionFolder(Path(tmp), "operator", "chat")
            folder.create_requested("plan.md", "A short plan.", "Please create plan.md with one step")
            for request in ("Read the plan.md file", "Create plan.md with one step"):
                with self.assertRaises(ValueError):
                    folder.create_requested("other.md", "outside scope", request)
            for content in ("", "a" * 16385, "binary\0data"):
                with self.assertRaises(ValueError):
                    folder.save("large", content)
            self.assertEqual(folder.names(), ["plan.md"])
            self.assertEqual(folder.reference("Which files are in the folder?"),
                             {"filenames": ["plan.md"]})
            self.assertIsNone(folder.reference("Build a website with three files"))


class FolderTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_committed_owner_turns_can_create_and_discuss_a_file(self):
        from unittest.mock import AsyncMock
        from me3.incremental import TranscriptRevision
        from me3.runtime import AgentRuntime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreground = AsyncMock()
            foreground.task_actions = False
            del foreground.stream
            foreground.run.return_value = "Tuesday."
            runtime = AgentRuntime(root, foreground, foreground, memory_enabled=False)
            try:
                spoken = AsyncMock(return_value=True)
                session = runtime.open_session(spoken, AsyncMock(), owner="operator")
                folder = SessionFolder(root, "operator", "chat")
                session.work_folder = folder
                sid = session.jobs.session_id
                text = "Save schedule dot txt as Meet Tuesday"
                partial = TranscriptRevision(sid, "one", 1, text, 0, 1)
                await session.transcript(partial, addressed=True)
                self.assertEqual(folder.names(), [])
                final = TranscriptRevision(sid, "one", 2, text, 0, 1, committed=True)
                self.assertEqual(await session.transcript(final, addressed=True), "workspace")
                await session._active
                self.assertEqual(folder.read("schedule.txt"), "Meet Tuesday")
                await session.accept("What is the date in schedule dot txt?")
                await session._active
                self.assertIn("Meet Tuesday", foreground.run.await_args.args[0])
                session.jobs.owner = "different"
                await session.accept("What is in schedule.txt?")
                await session._active
                self.assertNotIn("Meet Tuesday", foreground.run.await_args.args[0])
            finally:
                await runtime.close()

    async def test_voice_terminal_requests_require_committed_owner_and_current_epoch(self):
        from unittest.mock import AsyncMock, Mock
        from me3.incremental import TranscriptRevision
        from me3.runtime import AgentRuntime

        with tempfile.TemporaryDirectory() as tmp:
            worker = AsyncMock()
            worker.task_actions = False
            del worker.stream
            runtime = AgentRuntime(Path(tmp), worker, worker, memory_enabled=False)
            try:
                session = runtime.open_session(AsyncMock(return_value=True), AsyncMock(), owner="op")
                session.work_folder = SessionFolder(Path(tmp), "op", "one")
                session.terminal_request = Mock()
                sid = session.jobs.session_id
                text = "Build a prototype of a dashboard"
                await session.transcript(TranscriptRevision(sid, "one", 1, text, 0, 1), addressed=True)
                session.terminal_request.assert_not_called()
                final = TranscriptRevision(sid, "one", 2, text, 0, 1, committed=True)
                self.assertEqual(await session.transcript(final, addressed=True), "terminal")
                epoch = session.epoch
                session.terminal_request.assert_called_once_with("prototype", text, epoch)
                self.assertTrue(session.terminal_current(epoch))
                await session.accept("Clone octo/example", addressed=True)
                self.assertFalse(session.terminal_current(epoch))
                session.terminal_request.assert_called_with("github", "Clone octo/example", session.epoch)
                session.jobs.owner = "other"
                self.assertFalse(session.terminal_current(session.epoch))
                await session.accept("Push octo/example", addressed=True)
                self.assertEqual(session.terminal_request.call_count, 2)
            finally:
                await runtime.close()
