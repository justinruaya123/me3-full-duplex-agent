"""SQLite restart, floor policy and simulated clause receipts."""
import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from me3.runtime import AgentRuntime


class Worker:
    def __init__(self):
        self.count = 0
        self.reply = "First claim. Second claim. Last claim."

    async def run(self, *args, **kwargs):
        self.count += 1
        return self.reply


class ReportingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worker = Worker()
        self.clock = 100.
        self.spoken = []
        self.reject = ""
        self.restart()

    def restart(self):
        self.runtime = AgentRuntime(Path(self.temp.name), self.worker, Worker())
        self.addAsyncCleanup(self.runtime.close)
        self.session = self.open("alice")

    def open(self, owner):
        async def speak(text):
            self.spoken.append(text)
            return text != self.reject

        async def stop():
            pass

        return self.runtime.open_session(
            speak, stop, owner=owner, clock=lambda: self.clock
        )

    async def job(self, prompt="draft"):
        job = self.session.jobs.submit(prompt)
        await self.runtime.supervisor.wait(job["id"])
        return job["id"]

    async def ask(self, text):
        decision = await self.session.accept(text)
        if self.session._active:
            await self.session._active
        return decision

    async def test_queue_accepts_one_active_four_waiting(self):
        ids = [self.session.jobs.submit(str(i))["id"] for i in range(5)]
        with self.assertRaisesRegex(RuntimeError, "full"):
            self.session.jobs.submit("overflow")
        self.assertEqual(len(ids), 5)
        self.assertEqual(self.runtime.supervisor.timeout, 600)

    async def test_notice_is_not_a_result_receipt(self):
        key = await self.job()
        self.clock += 1
        self.assertTrue(self.session.poll())
        await self.session._active
        row = self.session.jobs.get(key)
        self.assertEqual(row["notified"], 1)
        self.assertEqual(row["report_state"], "pending")
        await self.ask("/result " + key)
        self.assertEqual(self.spoken[-3:], ["First claim.", "Second claim.", "Last claim."])
        self.assertEqual(self.session.jobs.get(key)["report_state"], "confirmed")

    async def test_uncertain_clause_continues_after_restart_no_execution(self):
        key = await self.job()
        self.reject = "Second claim."
        await self.ask("/result " + key)
        self.assertEqual(self.spoken, ["First claim.", "Second claim."])
        row = self.session.jobs.get(key)
        self.assertEqual(row["report_state"], "uncertain")
        self.assertGreater(row["report_offset"], 0)
        await self.runtime.close()
        self.restart()
        self.session.delivery_authorized = lambda: False
        self.assertFalse(self.session.poll())
        await self.ask("continue")
        self.assertEqual(len(self.spoken), 2)
        self.session.delivery_authorized = lambda: True
        self.reject = ""
        await self.ask("continue")
        self.assertEqual(self.spoken[2:], ["Second claim.", "Last claim."])
        self.assertEqual(self.worker.count, 1)
        self.assertEqual(self.session.jobs.get(key)["report_state"], "confirmed")

    async def test_partial_report_receipt_before_next_clause(self):
        key = await self.job()
        states = []
        async def speak(text):
            row = self.session.jobs.get(key)
            states.append((row["report_offset"], row["report_state"]))
            return True
        self.session.speak = speak
        await self.ask("/result " + key)
        self.assertEqual([x[0] for x in states], [0, 13, 27])
        self.assertEqual(states[1][1], "uncertain")

    async def test_deferred_notice_persists_and_new_revision_resets(self):
        key = await self.job()
        await self.ask("/defer " + key)
        await self.runtime.end_session(self.session)
        self.session = self.open("alice")
        self.clock += 1
        self.assertFalse(self.session.poll())
        self.session.jobs.revise(key, "new", expected_revision=1)
        await self.runtime.supervisor.wait(key)
        self.assertTrue(self.session.poll())

    async def test_go_back_reads_live_checkpoint_and_owner_after_restart(self):
        key = await self.job()
        await self.ask("/focus " + key)
        self.session.jobs.revise(key, "second version", expected_revision=1)
        await self.runtime.supervisor.wait(key)
        await self.runtime.close()
        self.restart()
        self.session = self.open("bob")
        await self.ask("go back")
        self.assertNotIn(key, self.spoken[-1])
        self.session = self.open("alice")
        await self.ask("go back")
        self.assertEqual(self.session.focus, key)
        self.assertIn("revision 2", self.spoken[-1])
        self.assertIn("completed", self.spoken[-1])
        self.assertEqual(self.worker.count, 2)

    async def test_quiet_cooldown_question_approval_and_requested_status(self):
        await self.job()
        self.clock += .79
        self.assertFalse(self.session.poll())
        self.clock += .02
        self.session.pending_question = True
        self.assertFalse(self.session.poll())
        self.session.pending_question = False
        self.session.pending_approval = True
        self.assertFalse(self.session.poll())
        self.session.pending_approval = False
        self.assertTrue(self.session.poll())
        await self.session._active
        second = await self.job("another")
        self.clock += 1
        self.assertFalse(self.session.poll())
        await self.ask("/status " + second)
        self.assertIn("completed", self.spoken[-1])
        self.clock += 28
        self.assertFalse(self.session.poll())
        self.clock += 2
        self.assertTrue(self.session.poll())

    async def test_ambiguous_cancel_does_not_select_foreground_or_job(self):
        await self.job()
        self.assertEqual(await self.ask("cancel"), "clarify")
        self.assertIn("generation", self.spoken[-1])
        self.assertTrue(self.session.pending_question)

    async def test_submit_owner_binding_failure_rolls_back_execution(self):
        db = self.runtime.supervisor.db
        db.execute("""CREATE TRIGGER fail_owner BEFORE INSERT ON job_owners
                   BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.session.jobs.submit("must not execute")
        await asyncio.sleep(0)
        self.assertEqual(self.runtime.supervisor.list(), [])
        self.assertEqual(self.worker.count, 0)

    async def test_stop_speech_keeps_provider_alive_until_cancel_generation(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        class Waiting:
            async def run(self, *args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        self.session.backend = Waiting()
        await self.session.accept("explain")
        await started.wait()
        await self.session.accept("stop speaking")
        await asyncio.sleep(0)
        self.assertFalse(cancelled.is_set())
        await self.session.accept("cancel generation")
        await asyncio.wait_for(cancelled.wait(), 1)

    async def test_cancel_generation_leaves_report_playback_running(self):
        key = await self.job()
        started, release = asyncio.Event(), asyncio.Event()
        async def speak(text):
            self.spoken.append(text)
            started.set()
            await release.wait()
            return True
        self.session.speak = speak
        await self.session.accept("/result " + key)
        await started.wait()
        report = self.session._active
        await self.session.accept("cancel generation")
        release.set()
        await report
        self.assertEqual(self.session.jobs.get(key)["report_state"], "confirmed")

    async def test_verification_timeout_and_fabricated_progress(self):
        self.worker.reply = "Checks passed. 99 percent done."
        key = await self.job()
        await self.ask("/status " + key)
        self.assertIn("artifact saved", self.spoken[-1])
        progress = self.spoken[-1].replace(key, "").casefold()
        self.assertNotIn("99", progress)
        self.assertNotIn("checks passed", progress)
        async def stalled(*args):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return "late"
        self.runtime.supervisor.timeout = .01
        self.runtime.supervisor.prepare_result = stalled
        key = await self.job("stalled verifier")
        self.assertEqual(self.session.jobs.get(key)["status"], "failed")
        with self.assertRaises(ValueError):
            self.session.jobs.result(key)

    async def test_long_report_persists_partial_and_superseding_resets(self):
        self.worker.reply = "A long verified sentence. " * 240
        key = await self.job()
        await self.ask("/result " + key)
        row = self.session.jobs.get(key)
        self.assertEqual(row["report_state"], "partial")
        self.assertGreaterEqual(row["report_offset"], 4000)
        self.session.jobs.revise(key, "different", expected_revision=1)
        await self.runtime.supervisor.wait(key)
        row = self.session.jobs.get(key)
        self.assertEqual((row["report_state"], row["report_offset"]), ("pending", 0))
        await self.ask("continue")
        self.assertIn("no outstanding report", self.spoken[-1])

    async def test_idle_notice_continue_retries_reporting_only(self):
        key = await self.job()
        self.clock += 1
        self.reject = self.session._notice_text([self.session.jobs.get(key)])
        self.assertTrue(self.session.poll())
        await self.session._active
        self.assertEqual(self.session.jobs.get(key)["notice_state"], "uncertain")
        self.reject = ""
        await self.ask("continue")
        self.assertEqual(self.session.jobs.get(key)["notice_state"], "confirmed")
        self.assertEqual(self.session.jobs.get(key)["report_state"], "pending")
        self.assertEqual(self.worker.count, 1)

    async def test_revision_of_focused_job_is_acknowledged_after_persist(self):
        key = await self.job()
        await self.ask("/focus " + key)
        self.spoken.clear()
        await self.ask("/revise " + key + " change the draft")
        self.assertEqual(self.session.jobs.get(key)["revision"], 2)
        self.assertTrue(any("new revision" in text for text in self.spoken))

    async def test_whole_result_remains_confirmed_only_by_report_receipt(self):
        key = await self.job()
        await self.ask("/focus " + key)
        await self.ask("explain the draft")
        self.assertEqual(self.session.jobs.get(key)["notified"], 0)
        self.assertEqual(self.session.jobs.get(key)["report_state"], "pending")

    async def test_result_with_long_unbroken_identifier_reaches_final_receipt(self):
        self.worker.reply = "Identifier " + "abc123" * 51 + ". Ready."
        key = await self.job()
        await self.ask("/result " + key)
        row = self.session.jobs.get(key)
        self.assertEqual(row["report_offset"], len(self.worker.reply))
        self.assertTrue(all(len(text) <= 240 for text in self.spoken))
        self.assertEqual("".join(self.spoken).replace(" ", ""),
                         self.worker.reply.replace(" ", ""))

    async def test_idle_poll_reads_only_first_three_current_owner_notices(self):
        keys = [await self.job(str(n)) for n in range(6)]
        self.clock += 1
        original = self.session.jobs.get
        visited = set()
        def observed(key):
            visited.add(key)
            return original(key)
        self.session.jobs.get = observed
        self.assertTrue(self.session.poll())
        await self.session._active
        self.assertLessEqual(len(visited), 3)
        self.assertTrue(all(original(key)["notified"] for key in keys[:3]))
        self.assertTrue(all(not original(key)["notified"] for key in keys[3:]))

    async def test_disfluent_cancellation_cannot_execute_first_fragment(self):
        waiting = asyncio.Event()
        class Blocked:
            async def run(self, *args, **kwargs):
                await waiting.wait()
                return "draft"
        self.runtime.worker.backend = Blocked()
        job = self.session.jobs.submit("draft")
        try:
            text = "cancel job " + job["id"] + " actually wait, keep it running"
            self.assertEqual(await self.ask(text), "clarify")
            self.assertIn(self.session.jobs.get(job["id"])["status"], {"queued", "running"})
            self.assertTrue(self.session.pending_question)
        finally:
            waiting.set()
            await self.runtime.supervisor.wait(job["id"])

    async def test_cancel_suppresses_completed_notice_across_restart(self):
        key = await self.job("poem about rain")
        await self.ask("/cancel " + key)
        await self.runtime.close()
        self.restart()
        self.clock += 2
        self.assertFalse(self.session.poll())
        self.assertEqual(self.session.jobs.get(key)["status"], "completed")
        self.assertEqual(await self.ask("/result " + key), "result")
        self.assertEqual(self.spoken[-1], "Last claim.")

    async def test_task_digest_and_revision_preserve_requirements_without_memory(self):
        from unittest.mock import AsyncMock
        key = await self.job("Four lines about rain for children")
        other = self.open("bob").jobs.submit("private on another owner's behalf")
        await self.runtime.supervisor.wait(other["id"])
        self.session.backend.run = AsyncMock(return_value="Here is the status.")
        await self.ask("What were we working on?")
        prompt = self.session.backend.run.await_args.args[0]
        self.assertIn(key, prompt)
        self.assertIn("Four lines about rain for children", prompt)
        self.assertNotIn(other["id"], prompt)
        await self.ask("/revise " + key + " Use a darker mood")
        revised = self.session.jobs.get(key)["prompt"]
        self.assertIn("Four lines about rain for children", revised)
        self.assertIn("Use a darker mood", revised)

    async def test_notice_names_task_and_uses_host_verification(self):
        await self.job("poem about rain")
        self.clock += 1
        self.assertTrue(self.session.poll())
        await self.session._active
        self.assertIn("poem about rain", self.spoken[-1])
        self.assertIn("saved", self.spoken[-1])
        self.assertNotIn("checks passed", self.spoken[-1])

    async def test_foreground_search_proposal_uses_only_authorized_public_query(self):
        from unittest.mock import AsyncMock
        from me3.foreground import ActionProposal
        from me3.lookup import LookupResult

        class Router:
            task_actions = True
            async def stream_turn(self, prompt, utterance):
                yield ActionProposal("lookup", utterance)

        self.session.backend = Router()
        search = AsyncMock(return_value=LookupResult("Sourced answer.", "sources"))
        self.session.web_lookup = search
        await self.ask("Describe the Gulf Stream")
        search.assert_awaited_once_with("Describe the Gulf Stream", "answers", None)
        await self.ask("What is in my private profile?")
        self.assertEqual(search.await_count, 1)
        self.assertIn("look up", self.spoken[-1].lower())

    async def test_site_paraphrases_enter_site_route_only_after_commit(self):
        from me3.incremental import TranscriptRevision
        from me3.foreground import ActionProposal
        class Router:
            task_actions = True
            async def stream_turn(self, prompt, utterance):
                yield ActionProposal("personal_website", utterance)
        self.session.backend = Router()
        for i, text in enumerate(("Can you build me a website?", "Make a portfolio for me",
                                  "Create my personal site")):
            args = (self.session.jobs.session_id, str(i))
            partial = TranscriptRevision(*args, 1, text, 0, 1)
            final = TranscriptRevision(*args, 2, text, 0, 1, True)
            self.assertEqual(await self.session.transcript(partial), "hold")
            self.assertEqual(await self.session.transcript(final), "turn")
            await self.session._active
            self.assertIn("public", self.spoken[-1])
            self.assertEqual(await self.session.transcript(final), "stale")
        self.assertFalse(self.session.jobs.list())

    async def test_one_committed_turn_routes_a_relative_revision(self):
        from me3.foreground import ActionProposal
        from me3.incremental import TranscriptRevision
        key = await self.job("A short poem about rain")
        turns = []
        class Router:
            task_actions = True
            async def stream_turn(self, prompt, utterance):
                turns.append(prompt)
                yield ActionProposal("revise", utterance)
        self.session.backend = Router()
        text = "Make it darker"
        args = self.session.jobs.session_id, "commit"
        await self.session.transcript(TranscriptRevision(*args, 1, text, 0, 1))
        self.assertEqual(turns, [])
        final = TranscriptRevision(*args, 2, text, 0, 1, True)
        await self.session.transcript(final)
        await self.session._active
        self.assertEqual(await self.session.transcript(final), "stale")
        self.assertEqual(len(turns), 1)
        self.assertEqual(self.session.jobs.get(key)["revision"], 2)
        self.assertIn(text, self.session.jobs.get(key)["prompt"])
