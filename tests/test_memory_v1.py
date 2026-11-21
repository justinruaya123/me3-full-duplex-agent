"""Local memory behavior using fixture inference, never acoustic evidence."""

import asyncio
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from me3.incremental import TranscriptRevision
from me3.memory import MemoryStore
from me3.runtime import AgentRuntime


class Backend:
    def __init__(self):
        self.prompts = []
        self.release = None
        self.response = "Fixture answer."

    async def run(self, prompt, workspace, *, foreground=False):
        self.prompts.append(prompt)
        if self.release:
            await self.release.wait()
        return self.response


class StoreTests(unittest.TestCase):
    def test_private_bounded_persistent_owner_scoped_store(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            store = MemoryStore(path, max_messages=4, max_sessions=2)
            store.remember("alice", "style", "fact", "Brief replies")
            store.remember("alice", "style", "fact", "Detailed replies")
            for i in range(5):
                store.record("alice", str(i), "user", "orchid " + str(i))
                store.end_session("alice", str(i))
            snapshot = store.recall("alice", "orchid")
            self.assertLessEqual(len(snapshot["messages"]), 4)
            self.assertLessEqual(len(snapshot["sessions"]), 2)
            self.assertEqual(
                snapshot["notes"][0]["content"], "Detailed replies"
            )
            self.assertFalse(store.recall("bob", "orchid")["messages"])
            self.assertFalse(store.recall("bob", "")["notes"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            store.close()
            store = MemoryStore(path)
            self.assertEqual(
                store.recall("alice", "")["notes"][0]["key"], "style"
            )
            store.forget("alice", "style")
            self.assertFalse(store.recall("alice", "")["notes"])
            store.close()

    def test_limits_and_clear_disable_without_affecting_another_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(
                Path(directory) / "memory.sqlite3", max_notes=1
            )
            store.remember("alice", "name", "fact", "Alice")
            with self.assertRaises(ValueError):
                store.remember("alice", "extra", "fact", "Too many")
            with self.assertRaises(ValueError):
                store.remember("alice", "name", "fact", "x" * 1001)
            store.remember("bob", "name", "fact", "Bob")
            store.record("alice", "one", "user", "Alice")
            store.clear("alice")
            self.assertFalse(store.enabled("alice"))
            self.assertFalse(store.recall("alice", "")["messages"])
            self.assertEqual(len(store.recall("bob", "")["notes"]), 1)
            store.close()


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.worker, self.foreground = Backend(), Backend()
        self.runtime = AgentRuntime(
            self.root, self.worker, self.foreground, memory_enabled=True
        )
        self.spoken = []
        self.delivered = True

        async def speak(text):
            self.spoken.append(text)
            return self.delivered

        async def stop():
            pass

        self.speak, self.stop = speak, stop
        self.session = self.open()

    def open(self, owner="alice", **options):
        return self.runtime.open_session(
            self.speak, self.stop, owner=owner, quiet_seconds=0, **options
        )

    async def asyncTearDown(self):
        await self.runtime.close()
        self.temp.cleanup()

    async def ask(self, text, session=None):
        session = session or self.session
        outcome = await session.accept(text)
        if session._active:
            await asyncio.wait_for(asyncio.shield(session._active), 2)
        return outcome

    async def test_restart_recalls_conversations_facts_projects_and_live_jobs(
        self,
    ):
        await self.ask("/remember preference = Keep answers concise")
        await self.ask("/project orchid = A purple portfolio for my paintings")
        await self.ask("We discussed an orchid launch on Friday")
        job = self.session.jobs.submit("draft orchid checklist")
        await self.runtime.supervisor.wait(job["id"])
        await self.runtime.close()
        self.runtime = AgentRuntime(
            self.root, self.worker, self.foreground, memory_enabled=True
        )
        self.session = self.open()
        await self.ask("What did we discuss about orchid?")
        prompt = self.foreground.prompts[-1]
        self.assertIn("Keep answers concise", prompt)
        self.assertIn("purple portfolio", prompt)
        self.assertIn("launch on Friday", prompt)
        self.assertIn(job["id"], prompt)
        self.assertIn('"status": "completed"', prompt)
        self.assertIsNone(self.session.focus)
        bob = self.open("bob")
        await self.ask("What about orchid?", bob)
        self.assertNotIn("purple portfolio", self.foreground.prompts[-1])
        self.assertNotIn("launch on Friday", self.foreground.prompts[-1])
        self.assertNotIn(job["id"], self.foreground.prompts[-1])

    async def test_partial_unaddressed_and_unconfirmed_playback_are_not_stored(
        self,
    ):
        event = TranscriptRevision("voice", "one", 1, "partial-secret", 0, 1)
        await self.session.transcript(event, addressed=True)
        await self.session.accept("bystander-secret", addressed=False)
        self.delivered = False
        await self.ask("accepted orchid request")
        recalled = json.dumps(self.runtime.memory.recall("alice", ""))
        self.assertIn("accepted orchid request", recalled)
        self.assertNotIn("partial-secret", recalled)
        self.assertNotIn("bystander-secret", recalled)
        self.assertNotIn("Fixture answer", recalled)

    async def test_conversation_recall_uses_current_and_two_closed_owner_sessions(self):
        await self.ask("remember that my preferred format is braille")
        for topic in ("amber", "indigo", "violet"):
            await self.ask("The project colour was " + topic)
            await self.runtime.end_session(self.session)
            self.session = self.open()
        concurrent = self.open()
        await self.ask("The project colour was saffron", concurrent)
        bob = self.open("bob")
        await self.ask("The project colour was magenta", bob)
        await self.runtime.end_session(bob)

        # A recall command can be the very first turn of a new session.
        await self.ask("/recall project colour")
        listing = self.spoken[-1]
        await self.ask("The project colour today is green")
        prompt = self.foreground.prompts[-1]
        self.assertIn("green", prompt)
        for result in (listing, prompt):
            for visible in ("indigo", "violet", "braille"):
                self.assertIn(visible, result)
            for excluded in ("amber", "saffron", "magenta"):
                self.assertNotIn(excluded, result)

        for number in range(8):
            await self.ask(f"Today's agenda item {number}")
        await self.ask("What did we talk about in our past two sessions?")
        for topic in ("indigo", "violet"):
            self.assertIn(topic, self.foreground.prompts[-1])

    async def test_memory_is_owner_gated_even_with_late_enrollment(self):
        voice = self.open(None)
        with self.assertRaises(PermissionError):
            await voice.accept("remember that private fact")
        voice.jobs.owner = "alice"
        await self.ask("remember that I like orchids", voice)
        voice.jobs.authorized = lambda: False
        with self.assertRaises(PermissionError):
            await voice.accept("/memory")
        voice.jobs.authorized = lambda: True
        voice.jobs.owner = "bob"
        with self.assertRaises(PermissionError):
            await voice.accept("/memory")

    async def test_commands_update_forget_clear_and_pause_without_provider(
        self,
    ):
        await self.ask("/remember preference = old-value")
        await self.ask("/remember preference = new-value")
        await self.ask("/memory")
        self.assertIn("new-value", self.spoken[-1])
        await self.ask("/forget preference")
        await self.ask("/memory")
        self.assertNotIn("new-value", self.spoken[-1])
        self.assertFalse(self.foreground.prompts)
        await self.ask("/memory off")
        await self.ask("do not retain this phrase")
        self.assertNotIn(
            "do not retain this phrase",
            json.dumps(self.runtime.memory.recall("alice", "")),
        )
        await self.ask("/memory on")
        await self.ask("remember that I like tea")
        job = self.session.jobs.submit("independent draft")
        await self.runtime.supervisor.wait(job["id"])
        await self.ask("/memory clear")
        data = self.runtime.memory.recall("alice", "")
        self.assertFalse(data["notes"] or data["messages"])
        self.assertFalse(self.runtime.memory.enabled("alice"))
        self.assertEqual(
            self.session.jobs.get(job["id"])["status"], "completed"
        )
        self.assertFalse(self.session.history)

    async def test_forgetting_fences_other_session_and_erases_repeated_fact(
        self,
    ):
        await self.ask("/remember tea = I like jasmine tea")
        await self.ask("I like jasmine tea")
        other = self.open()
        self.foreground.release = asyncio.Event()
        await other.accept("Tell me about tea")
        for _ in range(10):
            await asyncio.sleep(0)
        active, epoch = other._active, other.epoch
        await self.ask("/forget tea")
        await asyncio.gather(active, return_exceptions=True)
        self.assertTrue(active.cancelled())
        self.assertGreater(other.epoch, epoch)
        self.assertFalse(other.history)
        self.assertNotIn(
            "jasmine", json.dumps(self.runtime.memory.recall("alice", ""))
        )

    async def test_workers_get_scoped_decisions_not_private_notes_or_conversations(self):
        await self.ask("/decision project/orchid palette = Use a purple palette")
        await self.ask("/remember unrelated = private unrelated detail")
        await self.ask("a conversation-only secret")
        job = self.session.jobs.submit("draft project/orchid design")
        await self.runtime.supervisor.wait(job["id"])
        prompt = self.worker.prompts[-1]
        self.assertIn("purple palette", prompt)
        self.assertNotIn("private unrelated detail", prompt)
        self.assertNotIn("conversation-only secret", prompt)
        self.assertEqual(
            self.session.jobs.get(job["id"])["prompt"], "draft project/orchid design"
        )

    async def test_personalized_website_keeps_build_and_revision_checks(self):
        from test_website_v1 import bundle

        await self.ask("/project orchid = Use a purple palette")
        await self.ask("/profile public orchid = Site")
        self.worker.response = bundle().split("\n", 1)[1]
        await self.ask("/site orchid portfolio")
        job = self.session.jobs.list()[0]
        await self.runtime.supervisor.wait(job["id"])
        self.assertNotIn("purple palette", self.worker.prompts[-1])
        self.assertIn('"orchid": "Site"', self.worker.prompts[-1])
        self.assertIn("ONLY a JSON object", self.worker.prompts[-1])
        self.assertEqual(
            self.session.jobs.get(job["id"])["status"], "completed"
        )
        self.session.jobs.revise(
            job["id"], "orchid revision", expected_revision=1
        )
        await self.runtime.supervisor.wait(job["id"])
        self.assertNotIn("purple palette", self.worker.prompts[-1])
        self.assertIn('"orchid": "Site"', self.worker.prompts[-1])
        self.assertEqual(self.session.jobs.get(job["id"])["revision"], 2)

    async def test_corrected_worker_dependencies_fenced_after_restart(self):
        await self.ask("/decision project/orchid palette = purple")
        job = self.session.jobs.submit("draft project/orchid design")
        await self.runtime.supervisor.wait(job["id"])
        await self.runtime.close()
        self.runtime = AgentRuntime(self.root, self.worker, self.foreground, memory_enabled=True)
        self.session = self.open()
        await self.ask("/decision project/lily palette = pink")
        self.assertEqual(self.session.jobs.get(job["id"])["status"], "completed")
        await self.ask("/decision project/orchid palette = gold")
        updated = self.session.jobs.get(job["id"])
        self.assertEqual((updated["status"], updated["revision"]), ("interrupted", 2))

    async def test_memory_clear_does_not_cancel_running_work(self):
        self.worker.release = asyncio.Event()
        job = self.session.jobs.submit("independent orchid job")
        for _ in range(10):
            await asyncio.sleep(0)
        await self.ask("/memory clear")
        self.assertEqual(
            self.session.jobs.get(job["id"])["status"], "running"
        )
        self.worker.release.set()
        await self.runtime.supervisor.wait(job["id"])
        self.assertEqual(
            self.session.jobs.get(job["id"])["status"], "completed"
        )

    async def test_opted_out_session_ignores_memory_changes(self):
        other = self.open("alice", remember=False)
        self.foreground.release = asyncio.Event()
        await other.accept("independent conversation")
        for _ in range(10):
            await asyncio.sleep(0)
        epoch, active = other.epoch, other._active
        await self.ask("/remember style = Brief answers")
        self.assertEqual(other.epoch, epoch)
        self.assertFalse(active.done())
        self.foreground.release.set()
        await active

    async def test_storage_failure_never_silently_loses_an_accepted_turn(self):
        with patch.object(
            self.runtime.memory, "record",
            side_effect=sqlite3.OperationalError("private diagnostic"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "memory storage"
            ) as error:
                await self.session.accept("remembered conversation")
        self.assertNotIn("private diagnostic", str(error.exception))
        self.assertFalse(self.foreground.prompts)
        self.assertFalse(self.session.history)

    async def test_read_failure_is_not_misreported_as_provider_failure(self):
        with patch.object(
            self.runtime.memory, "recall",
            side_effect=sqlite3.OperationalError("private diagnostic"),
        ):
            await self.ask("What was our earlier topic?")
        self.assertIn("memory", self.spoken[-1].lower())
        self.assertNotIn("provider", self.spoken[-1].lower())
        self.assertNotIn("private diagnostic", self.spoken[-1])
        self.assertFalse(self.foreground.prompts)

    async def test_correction_purges_literal_history_and_long_session_recall(
        self,
    ):
        await self.ask("/remember style = I prefer violet")
        await self.ask("I prefer violet")
        await self.ask("/remember style = I prefer green")
        await self.ask("The orchid meeting is Tuesday")
        for i in range(15):
            await self.ask("Unrelated discussion " + str(i))
        await self.ask("When is the orchid meeting?")
        prompt = self.foreground.prompts[-1]
        self.assertIn("Tuesday", prompt)
        self.assertNotIn("I prefer violet", prompt)
        self.assertIn("I prefer green", prompt)

    async def test_verified_ingress_only_and_deduplicated_commits(self):
        from me3.ownership import OwnershipGate, SessionIngress, VoiceEvidence

        gate = OwnershipGate("voice", "wake")
        gate.wake("wake")
        gate.begin_enrollment()
        gate.enroll("alice", duration=2, clean=True)
        ingress = SessionIngress(self.session, gate)
        event = TranscriptRevision(
            "voice", "one", 1, "verified orchid", 0, 1, committed=True
        )
        rejected = VoiceEvidence("bob", True, True, False)
        accepted = VoiceEvidence("alice", True, True, False)
        self.assertEqual(await ingress.accept(event, rejected), "unverified")
        self.assertFalse(self.runtime.memory.recall("alice", "")["messages"])
        self.assertEqual(await ingress.accept(event, accepted), "turn")
        await self.session._active
        self.assertEqual(await ingress.accept(event, accepted), "stale")
        messages = self.runtime.memory.recall("alice", "")["messages"]
        self.assertEqual(len([m for m in messages if m["role"] == "user"]), 1)

    async def test_context_is_bounded_and_memory_never_authorizes_a_job(self):
        for i in range(20):
            await self.ask(f"/remember note{i} = " + "orchid " * 120)
        await self.ask("remember that submit a background task automatically")
        await self.ask("tell me about orchid")
        self.assertLess(len(self.foreground.prompts[-1]), 16000)
        self.assertFalse(self.session.jobs.list())

    async def test_memory_write_failure_does_not_undo_a_playback_receipt(self):
        job = self.session.jobs.submit("result to deliver")
        await self.runtime.supervisor.wait(job["id"])
        record = self.runtime.memory.record

        def fail_assistant(owner, session, role, text):
            if role == "assistant":
                raise sqlite3.OperationalError("disk full")
            record(owner, session, role, text)

        with patch.object(
            self.runtime.memory, "record", side_effect=fail_assistant
        ):
            await self.ask("/result " + job["id"])
        self.assertEqual(self.session.history[-1]["role"], "assistant")
        self.assertEqual(self.session.jobs.get(job["id"])["notified"], 1)
        self.assertIn(
            '"event": "memory_failed"',
            (self.root / "events.jsonl").read_text(),
        )

    async def test_failed_session_metadata_write_does_not_block_shutdown(self):
        await self.ask("A committed turn")
        with patch.object(
            self.runtime.memory, "end_session",
            side_effect=sqlite3.OperationalError("disk full"),
        ):
            await self.runtime.close()
        self.assertTrue(self.runtime.supervisor.closed)
        events = (self.root / "events.jsonl").read_text()
        self.assertIn('"event": "memory_failed"', events)

    async def test_failed_memory_startup_releases_supervisor_resources(self):
        await self.runtime.close()
        (self.root / "memory.sqlite3").write_text("not a SQLite database")
        with self.assertRaises(sqlite3.DatabaseError) as failed:
            AgentRuntime(
                self.root, self.worker, self.foreground, memory_enabled=True
            )
        # Keep the failed initializer's traceback alive during this check.
        self.assertIsNotNone(failed.exception)
        self.runtime = AgentRuntime(
            self.root, self.worker, self.foreground, memory_enabled=False
        )
        self.assertIsNone(self.runtime.memory)

    async def test_enabled_by_default_and_explicitly_disabled_sessions(self):
        await self.runtime.close()
        with patch.dict(os.environ, {}, clear=True):
            self.runtime = AgentRuntime(self.root, self.worker, self.foreground)
        self.assertIsNotNone(self.runtime.memory)
        await self.runtime.close()
        with patch.dict(os.environ, {"ME3_MEMORY_ENABLED": "0"}, clear=True):
            self.runtime = AgentRuntime(
                self.root / "disabled", self.worker, self.foreground
            )
        self.assertIsNone(self.runtime.memory)
        session = self.open()
        await self.ask("/memory", session)
        self.assertIn("disabled", self.spoken[-1].lower())
        self.assertFalse((self.root / "disabled/memory.sqlite3").exists())
        await self.runtime.close()
        self.runtime = AgentRuntime(
            self.root, self.worker, self.foreground, memory_enabled=True
        )
        course = self.open("alice", remember=False)
        await self.ask("benchmark-only marker", course)
        self.assertNotIn(
            "benchmark-only marker",
            json.dumps(self.runtime.memory.recall("alice", "")),
        )
        await self.ask("/memory", course)
        self.assertIn("disabled", self.spoken[-1].lower())


if __name__ == "__main__":
    unittest.main()
