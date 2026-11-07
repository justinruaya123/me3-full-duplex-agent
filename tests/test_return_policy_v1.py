"""Durable result timing with real local job/controller state."""

import unittest

import test_results_v1 as fixtures

from me3.incremental import TranscriptRevision
from me3.runtime import AgentRuntime


class ReturnPolicyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ResultTests.asyncSetUp
    asyncTearDown = fixtures.ResultTests.asyncTearDown
    settle = fixtures.ResultTests.settle

    async def ready(self):
        job = self.session.jobs.submit("draft")
        await self.runtime.supervisor.wait(job["id"])
        return self.session.jobs.get(job["id"])

    async def test_default_completion_waits_for_explicit_retrieval(self):
        job = await self.ready()
        self.assertFalse(self.session.poll())
        await self.settle()
        self.assertFalse(self.spoken)
        self.assertEqual(job["return_policy"], "ask_first")
        await self.session.accept("/result " + job["id"])
        await self.settle()
        self.assertIn("done", self.spoken)
        self.assertIsNone(self.session.focus)

    async def test_after_topic_needs_wrapup_not_ordinary_quiet_gap(self):
        job = await self.ready()
        await self.session.accept("/notify " + job["id"] + " after_topic")
        await self.settle()
        self.assertFalse(self.session.poll())
        await self.session.accept("That settles it.")
        await self.settle()
        self.assertTrue(self.session.poll())
        await self.settle()
        self.assertIn("background task", self.spoken[-1])
        self.assertIsNone(self.session.focus)

    async def test_unanswered_question_vetoes_even_allowed_topic_offer(self):
        job = await self.ready()
        await self.session.accept("/notify " + job["id"] + " after_topic")
        await self.settle()
        await self.session.accept("That settles it.")
        await self.settle()
        self.session.pending_question = True
        self.assertFalse(self.session.poll())
        self.session.pending_question = False
        self.assertTrue(self.session.poll())

    async def test_defer_survives_runtime_restart_and_preserves_result(self):
        job = await self.ready()
        await self.session.accept("/defer " + job["id"])
        await self.settle()
        root = self.runtime.supervisor.root
        await self.runtime.close()
        self.runtime = AgentRuntime(root, fixtures.Worker(), fixtures.Worker())

        async def speak(text):
            self.spoken.append(text)
            return True

        async def stop():
            pass

        self.session = self.runtime.open_session(
            speak, stop, owner="alice", quiet_seconds=0
        )
        self.assertFalse(self.session.poll())
        self.assertEqual(
            self.session.jobs.get(job["id"])["return_policy"], "ask_first"
        )

    async def test_preference_suffix_is_not_sent_to_website_worker(self):
        await self.session.accept(
            "Create a website for a cafe; tell me after we finish talking."
        )
        await self.settle()
        job = self.session.jobs.list()[0]
        self.assertEqual(job["return_policy"], "after_topic")
        self.assertNotIn("tell me after", job["prompt"])

    async def test_provisional_policy_command_cannot_change_preferences(self):
        job = await self.ready()
        await self.session.accept("/notify " + job["id"] + " after_topic")
        await self.settle()
        event = TranscriptRevision(
            "s", "t", 1, "/defer " + job["id"], 0, 1, False
        )
        self.assertEqual(await self.session.transcript(event), "hold")
        self.assertEqual(
            self.session.jobs.get(job["id"])["return_policy"], "after_topic"
        )

    async def test_preference_change_rejects_stale_revision_or_owner(self):
        from me3.jobs import OwnedJobs

        job = await self.ready()
        with self.assertRaises(ValueError):
            self.session.jobs.set_return_policy(
                job["id"], "after_topic", expected_revision=0
            )
        other = OwnedJobs(self.runtime.supervisor, "bob", "other")
        with self.assertRaises(KeyError):
            other.set_return_policy(
                job["id"], "after_topic", expected_revision=1
            )

    async def test_new_topic_clears_old_wrapup_permission(self):
        job = await self.ready()
        await self.session.accept("/notify " + job["id"] + " after_topic")
        await self.settle()
        await self.session.accept("That settles it.")
        await self.settle()
        await self.session.accept("Actually, another question about my day.")
        await self.settle()
        self.assertFalse(self.session.poll())

    async def test_natural_website_retrieval_preserves_conversation_focus(
        self,
    ):
        await self.session.accept("Create a website for a cafe.")
        job = self.session.jobs.list()[0]
        await self.runtime.supervisor.wait(job["id"])
        await self.settle()
        self.assertEqual(await self.session.accept("Show me the website."),
                         "result")
        await self.settle()
        self.assertIsNone(self.session.focus)

    async def test_ambiguous_natural_website_request_asks_which_job(self):
        for request in ("Create a website for a cafe.",
                        "Create a website for a florist."):
            await self.session.accept(request)
            await self.settle()
        self.assertEqual(await self.session.accept("Show me the website."),
                         "clarify")

    async def test_changed_policy_fences_already_scheduled_offer(self):
        job = await self.ready()
        await self.session.accept("/notify " + job["id"] + " after_topic")
        await self.settle()
        await self.session.accept("That settles it.")
        await self.settle()
        self.spoken.clear()
        self.assertTrue(self.session.poll())
        self.session.jobs.set_return_policy(
            job["id"], "ask_first", expected_revision=job["revision"]
        )
        await self.settle()
        self.assertFalse(self.spoken)
        self.assertFalse(self.session.jobs.get(job["id"])["notified"])

    async def test_focused_job_preference_changes_are_acknowledged(self):
        job = await self.ready()
        self.session.focus = job["id"]
        for command in ("/notify " + job["id"] + " after_topic",
                        "/defer " + job["id"]):
            self.spoken.clear()
            await self.session.accept(command)
            await self.settle()
            self.assertEqual(len(self.spoken), 1)
