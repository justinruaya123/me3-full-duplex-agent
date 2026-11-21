import unittest

from integrations.voicechat.lookup import public_request


class VoiceSearchTests(unittest.TestCase):
    def test_standalone_question_uses_owner_words_even_when_model_rephrases(self):
        source = "What is the latest stable Python release according to python.org?"
        query, _, _ = public_request(source, "Current CPython version and owner profile")
        self.assertEqual(query, source)

    def test_reordered_public_terms_in_a_compound_command(self):
        request = "Check the stable version of Python on python.org and give me one sentence."
        self.assertEqual(public_request(request, "stable Python version python.org")[0],
                         "stable Python version python.org")
        with self.assertRaises(ValueError):
            public_request(request, "stable Ruby version")

    def test_topic_from_a_spoken_multi_sentence_request(self):
        question = "What is the capital of the Philippines?"
        self.assertEqual(public_request(question + " Please verify with Brave.", question),
                         (question, "answers", None))

    def test_spoken_verification_instruction_preserves_the_public_question(self):
        question = "What is the boiling point of nitrogen at atmospheric pressure?"
        self.assertEqual(public_request(question + " Verify it with Brave.", "nitrogen one atmosphere"),
                         (question, "answers", None))

    def test_profile_terms_cannot_be_added_and_no_search_is_honored(self):
        for source, topic in [
            ("What's my name?", "Tess Example"),
            ("What is the forecast? Don't search the web.", "What is the forecast?"),
            ("Read my private notes.", "my private notes"),
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                public_request(source, topic)


class PlanRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_website_uses_only_its_public_research_subject(self):
        from integrations.voicechat.lookup import lookup
        for source in (
            "Build a website about the latest Python releases.",
            "Look up the latest Python releases and build a website about them.",
            "Build a website using my private notes. Search for the latest Python releases.",
        ):
            with self.subTest(source=source):
                plan = await lookup(
                    source, "private employer and guessed details", {}, resolve_only=True)
                self.assertEqual(plan.get("query"), "latest Python releases")
                self.assertTrue(plan.get("site_research"))
                self.assertTrue(plan["force_live"])
        for source in ("Build a website about my latest projects.",
                       "Build a website about the latest Python releases. Don't browse."):
            plan = await lookup(source, None, {}, resolve_only=True)
            self.assertNotIn("query", plan)

    async def test_voice_question_and_explicit_results_use_different_presentations(self):
        from integrations.voicechat.lookup import lookup
        for source, mode, show in [
            ("What causes blue icebergs?", "answers", False),
            ("Could you search for blue icebergs?", "web", True),
            ("Show me links about blue icebergs.", "web", True),
            ("Which studies describe blue icebergs?", "answers", False),
            ("Search for blue icebergs, just tell me the answer.", "answers", False),
        ]:
            with self.subTest(source=source):
                plan = await lookup(source, "blue icebergs", {}, resolve_only=True)
                self.assertEqual((plan["mode"], plan.get("show_results", False)), (mode, show))
        self.assertNotIn("query", await lookup("How is my current project going?", None, {}, resolve_only=True))

    async def test_pi_action_cannot_become_a_search_via_model_topic_or_previous_receipt(self):
        from integrations.voicechat.lookup import lookup
        plan = await lookup("Can you draft a checklist about penguins?", "penguins", {},
                            resolve_only=True, continuation_query="Antarctic wildlife",
                            continuation_selected=True)
        self.assertNotIn("query", plan)
        self.assertIn("error", plan)

    async def test_results_request_can_name_a_subject_from_its_public_receipt(self):
        from integrations.voicechat.lookup import lookup
        plan = await lookup("Search for the expedition's official page and show me the links.",
                            "Endurance expedition official page", {}, resolve_only=True,
                            continuation_query="Which expedition sailed to Antarctica?",
                            previous_evidence="The Endurance expedition sailed to Antarctica.")
        self.assertTrue(plan.get("show_results"))
        self.assertIn("Endurance", plan["query"])
        self.assertIn("official page", plan["query"])
        self.assertNotIn("show me", plan["query"])

    def test_follow_up_uses_the_selected_public_receipt_and_only_grounded_refinements(self):
        from integrations.voicechat.lookup import resolve_request
        for followup in ("Walk me through that part.", "Can you tell me more about that?"):
            plan = resolve_request(followup, "heritage timetable private employer", {},
                                   continuation_query="When is the North Pier ferry running?",
                                   previous_evidence="The heritage timetable lists additional sailings.")
            self.assertIn("North Pier ferry", plan["query"])
            self.assertIn("heritage timetable", plan["query"])
            self.assertNotIn("private employer", plan["query"])
        plan = resolve_request("Compare the vessel designs.", "outriggers", {},
                               continuation_query="North Pier ferry", continuation_selected=True,
                               previous_evidence="Researchers documented the outriggers.")
        self.assertEqual(plan["query"], "North Pier ferry outriggers")
        with self.assertRaises(ValueError):
            resolve_request("Don't search for more.", None, {}, continuation_query="North Pier ferry")

    def test_go_ahead_with_proposed_scope_and_a_new_topic(self):
        from integrations.voicechat.lookup import resolve_request
        context = dict(confirmed_scope="the harbor ferry", pending_receipt=True,
                       scope_source="Which timetable did you mean?")
        self.assertIn("harbor ferry", resolve_request("Just search that in brief.", None, {}, **context)["query"])
        with self.assertRaises(ValueError):
            resolve_request("Skip that.", None, {}, **context)
        plan = resolve_request("Who designed the Brooklyn Bridge?", None, {},
                               continuation_query="the harbor ferry")
        self.assertNotIn("ferry", plan["query"])
        with self.assertRaises(ValueError):
            resolve_request("Where is that private file?", None, {}, continuation_query="the harbor ferry")

    def test_guessed_event_details_do_not_block_a_named_public_question(self):
        from integrations.voicechat.lookup import resolve_request
        for source, scope, subject in [
            ("So who... When did Sri Lanka got the bad, overthrowing of government?",
             "Sri Lanka 2022 protests", "Sri Lanka"),
            ("When did the Voyager spacecraft launch?", "Voyager 2 in 1977", "Voyager"),
        ]:
            with self.subTest(source=source):
                plan = resolve_request(source, scope, {}, propose_scope=scope)
                self.assertIn(subject, plan["query"])
                self.assertNotRegex(plan["query"], r"2022|1977")
                self.assertNotIn("So who", plan["query"])

    def test_fresh_followup_reuses_only_the_validated_public_query(self):
        from integrations.voicechat.lookup import resolve_request
        plan = resolve_request("Think there's some more modern there.", "confidential salary", {},
                               recheck_query="When did the Voyager spacecraft launch?",
                               propose_scope="Voyager 2 in 1977")
        self.assertTrue(plan["force_live"])
        self.assertIn("Voyager", plan["query"])
        self.assertIn("recent", plan["query"])
        self.assertNotRegex(plan["query"], "1977|salary")

    async def test_research_me_asks_for_a_search_name_before_any_request(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup

        turn = "Can you also research about myself in the Internet? And add that to the website?"
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            result = await lookup(turn, "Private Name secret employer", {})
        brave.assert_not_awaited()
        self.assertEqual(result["clarification"], "What name should I search for?")

    async def test_next_spoken_name_wins_over_a_rewritten_model_query(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            brave.return_value = LookupResult("Result", "Source")
            await lookup("Ada Lovelace.", "famous historical programmer profile biography",
                         {"BRAVE_SEARCH_API_KEY":"test"}, scope_source="Research about myself online.", awaiting_name=True)
            brave.assert_awaited_once_with("Ada Lovelace", "web", None)

    async def test_research_me_uses_only_an_explicit_public_search_name(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult

        with TemporaryDirectory() as directory:
            env = {"ME3_VOICE_PROMPT_DIR": directory, "BRAVE_SEARCH_API_KEY": "test"}
            profile = Path(directory) / "USER.md"
            profile.write_text("- Full name, if useful: Hidden Owner\n")
            with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
                brave.return_value = LookupResult("Public result", "Retrieved")
                result = await lookup("Look me up online.", "Hidden Owner and private employer", env)
                self.assertIn("clarification", result)
                brave.assert_not_awaited()
                profile.write_text(profile.read_text() + "- Public search name: Ada Lovelace\n")
                await lookup("Look me up online.", "Hidden Owner and private employer", env)
                brave.assert_awaited_once_with("Ada Lovelace", "web", None)
                await lookup("Don't look me up online.", "Hidden Owner", env)
                self.assertEqual(brave.await_count, 1)

    async def test_recent_public_referent_and_expired_referent_across_domains(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult

        for subject, question in [("the Louvre", "When does it close?"),
                                  ("the Australian Open", "Who won the final?")]:
            with self.subTest(subject=subject), patch(
                    "integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
                brave.return_value = LookupResult("Result", "Retrieved")
                prior = "Let's discuss " + subject + "."
                await lookup(question, subject, {"BRAVE_SEARCH_API_KEY": "test"}, propose_scope=subject,
                             recent_turns=[prior])
                self.assertIn(subject, brave.await_args.args[0])
                pending = await lookup(question, subject, {}, propose_scope=subject,
                                       recent_turns=[prior, "New topic.", "Another topic."])
                self.assertIn(subject, pending["clarification"])
                self.assertEqual(brave.await_count, 1)

    async def test_recent_quote_supplies_the_entity_without_model_search_keywords(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult

        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            brave.return_value = LookupResult("Hours", "Museum")
            await lookup("When does it close on Mondays? Check the official site.", "museum opening hours",
                         {"BRAVE_SEARCH_API_KEY": "test"}, propose_scope="museum official opening hours",
                         recent_mention="the Louvre museum in Paris",
                         recent_turns=["Different topic: the Louvre museum in Paris. What is it known for?"])
            self.assertIn("the Louvre museum in Paris", brave.await_args.args[0])
            self.assertIn("Mondays", brave.await_args.args[0])

    async def test_person_named_in_the_previous_turn_is_enough_for_a_public_question(self):
        from integrations.voicechat.lookup import lookup
        for introduction in ["Ada Lovelace.", "I meant Ada Lovelace."]:
            with self.subTest(introduction=introduction):
                result = await lookup("What is she known for?", None, {}, resolve_only=True,
                                      recent_mention="Ada Lovelace", recent_turns=[introduction])
                self.assertEqual(result["mode"], "answers")
                self.assertIn("Ada Lovelace", result["query"])
                self.assertIn("known for", result["query"])

    async def test_yes_after_a_wake_word_reuses_the_spoken_public_subject(self):
        from integrations.voicechat.lookup import lookup
        result = await lookup("Yes.", "Nadia Reed", {}, resolve_only=True,
                              confirmed_scope="Nadia Reed", scope_source="Hey BMO?",
                              recent_turns=["Who is Nadia Reed?", "Hey BMO?"])
        self.assertEqual(result["query"], "Nadia Reed")
        self.assertEqual(result["mode"], "answers")

    async def test_spoken_spelling_correction_wins_after_a_lookup(self):
        from integrations.voicechat.lookup import lookup
        for correction in ["Nadiya Reid.", "Actually, I meant Nadiya Reid."]:
            with self.subTest(correction=correction):
                result = await lookup(correction, "Nadia Reed", {}, resolve_only=True, previous_lookup=True)
                self.assertEqual(result["query"], "Nadiya Reid")
                self.assertEqual(result["mode"], "answers")
        private = await lookup("My project.", "Nadia Reed", {}, resolve_only=True, previous_lookup=True)
        self.assertIn("error", private)

    async def test_same_turn_topic_switch_keeps_the_named_subject(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            brave.return_value = LookupResult("Result", "Source")
            await lookup("New topic: North Pier ferry. When does it run?", "operating schedule",
                         {"BRAVE_SEARCH_API_KEY":"test"}, propose_scope="North Pier ferry")
            self.assertIn("North Pier ferry", brave.await_args.args[0])
            self.assertIn("When does it run?", brave.await_args.args[0])

    async def test_named_news_subject_keeps_the_original_spoken_query(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            brave.return_value = LookupResult("Story", "Source")
            await lookup("Any recent Philippine news?", "Philippines", {"BRAVE_SEARCH_API_KEY":"test"},
                         propose_scope="the Philippines", one_story=True)
            brave.assert_awaited_once_with("Any recent Philippine news?", "news", "pw")

    async def test_suggested_public_scope_is_local_until_the_next_confirmation(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import LookupResult

        question = "Who won in the twenty twenty two national election?"
        scope = "the 2022 Philippine presidential election"
        env = {"BRAVE_SEARCH_API_KEY": "test"}
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", new_callable=AsyncMock) as brave:
            brave.return_value = LookupResult("Result", "Retrieved")
            pending = await lookup(question, scope, env, propose_scope=scope)
            self.assertEqual(pending["clarification"], "Do you mean the 2022 Philippine presidential election?")
            brave.assert_not_awaited()
            await lookup("Yes.", "someone else won", env, confirmed_scope=pending["scope"], scope_source=question)
            self.assertIn(scope, brave.await_args.args[0])
            self.assertNotIn("someone else", brave.await_args.args[0])
            await lookup("No.", scope, env, confirmed_scope=scope)
            await lookup("Yes.", scope, env)
            self.assertEqual(brave.await_count, 1)

    async def test_answers_entitlement_uses_web_once_and_labels_the_source(self):
        from unittest.mock import AsyncMock, patch
        from integrations.voicechat.lookup import lookup
        from me3.lookup import AnswersNotInPlan, LookupResult

        provider = AsyncMock(side_effect=[
            AnswersNotInPlan(),
            LookupResult("Brief", "Retrieved", ("https://example.org",)),
        ])
        with patch("integrations.voicechat.lookup.BraveLookup.web_lookup", provider):
            evidence = await lookup("Look up Saturn", "Saturn", {"BRAVE_SEARCH_API_KEY": "test"})
        self.assertEqual(evidence["mode"], "web")
        self.assertIn("Answers", evidence["sources"])
        self.assertEqual([c.args[1] for c in provider.await_args_list], ["answers", "web"])


class BraveVoicePromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_answers_requests_a_short_spoken_sentence_and_keeps_streamed_citations(self):
        import json

        import httpx

        from me3.lookup import BraveLookup

        def respond(request):
            body = json.loads(request.content)
            self.assertTrue(body["stream"])
            self.assertTrue(body["enable_citations"])
            self.assertFalse(body["enable_research"])
            prompt = body["messages"][0]["content"]
            self.assertIn("one short sentence", prompt)
            self.assertTrue(prompt.endswith("When does the exhibit close?"))
            answer = "The exhibit closes Friday."
            citation = json.dumps({"url": "https://example.org/exhibit", "title": "Museum",
                                   "snippet": answer, "start_index": 0, "end_index": len(answer)})
            parts = [answer + "<cita", "tion>" + citation, "</citation>"]
            events = ["data: " + json.dumps({"choices": [{"delta": {"content": s}}]}) for s in parts]
            return httpx.Response(200, text="\n\n".join([*events, "data: [DONE]"]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await BraveLookup("fixture", client=client).web_lookup(
                "When does the exhibit close?", "answers", None)
        self.assertEqual(result.speech, "The exhibit closes Friday.")
        self.assertEqual(result.urls, ("https://example.org/exhibit",))


class HeadlineTests(unittest.IsolatedAsyncioTestCase):
    def test_implicit_news_and_explicit_roundup(self):
        for request in ("Any recent PH news?", "Recent New Zealand news?"):
            self.assertEqual(public_request(request)[1:], ("news", "pw"))
        self.assertEqual(public_request("Today's space news?")[1:], ("news", "pd"))
        self.assertNotEqual(public_request("Give me three headlines about Japan",
                                           "three headlines about Japan")[1], "news")
        self.assertNotEqual(public_request("What is fake news?")[1], "news")
        self.assertNotEqual(public_request("Explain how newspapers report news.")[1], "news")
        self.assertNotEqual(public_request("Compare recent PH news", "recent PH news",
                                           one_story=False)[1], "news")
        with self.assertRaises(ValueError):
            public_request("Any recent PH news? Don't Google it.", "PH news")

    async def test_returns_one_dated_article_and_only_its_evidence(self):
        import httpx
        from datetime import datetime, timezone
        from me3.lookup import BraveLookup

        now = datetime.now(timezone.utc).isoformat()
        def respond(request):
            self.assertEqual(request.url.path, "/res/v1/news/search")
            self.assertEqual(request.url.params["freshness"], "pw")
            articles = [{"title": name, "description": "A useful detail about " + name,
                         "url": "https://example.org/" + name, "page_age": stamp}
                        for name, stamp in [("one", now), ("two", now),
                                            ("stale", "2015-01-01"), ("undated", "")]]
            return httpx.Response(200, json={"results": articles})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            found = await BraveLookup("fixture", client=client).web_lookup("science news", "news", "pw")
        self.assertEqual(len(found.urls), 1)
        name = found.urls[0].split("/")[-1]
        self.assertIn(name, ("one", "two"))
        self.assertIn("A useful detail about " + name, found.support)
        self.assertNotIn("two" if name == "one" else "one", found.support)


class PublicFollowupTests(unittest.TestCase):
    def test_factual_followup_can_reuse_the_previous_public_story(self):
        query, mode, _ = public_request("What percent was that?", "the owner's private contact",
                                        previous_subject="Texas Senate election results")
        self.assertIn("Texas Senate election results", query)
        self.assertIn("percent", query)
        self.assertNotIn("contact", query)
        self.assertEqual(mode, "answers")

    def test_topic_can_name_the_public_subject_in_a_followup(self):
        query, _, _ = public_request("What percent was that?", "Texas election Maya Reed vote share",
                                     previous_subject="Texas election",
                                     previous_evidence="Maya Reed won the election.")
        self.assertIn("Maya Reed", query)
        self.assertIn("percent", query)
        self.assertNotIn("share", query)

    def test_followup_keeps_private_turns_and_opt_outs_local(self):
        for turn in ["What about my salary?", "Where is that private file?", "Don't Google that."]:
            with self.subTest(turn=turn), self.assertRaises(ValueError):
                public_request(turn, previous_subject="Texas Senate election results")

class EvidenceDateTests(unittest.TestCase):
    def test_source_dates_are_distinct_from_relative_age_and_retrieval_time(self):
        from me3.lookup import result
        base = {"url":"https://example.org/report", "description":"A public report."}
        found = result([base | {"page_age":"2022-05-12", "age":"4 years ago"},
                        base | {"url":"https://example.org/later", "published_at":"2022-05-14"},
                        base | {"url":"https://example.org/undated"}], "", False)
        first, second, undated = found.source_dates
        self.assertEqual(first["page_date"], "2022-05-12")
        self.assertEqual(first["reported_age"], "4 years ago")
        self.assertIsNone(first["published_at"])
        self.assertEqual(second["published_at"], "2022-05-14")
        self.assertIsNone(undated["page_date"])
        self.assertIsNone(undated["published_at"])
