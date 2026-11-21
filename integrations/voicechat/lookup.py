"""Resolve a committed public request against bounded context before calling Brave."""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from me3.lookup import (
    AnswersNotInPlan, BraveLookup, LOCAL_CONTEXT, NEWS_REQUEST, QUESTION, lookup_intent, lookup_token,
)


SELF_LOOKUP = re.compile(
    r"^(?:(?:hey[, ]+)?bmo[, ]+)?(?:please\s+)?(?:(?:can|could|would) you\s+)?"
    r"(?:(?:also|please)\s+)*(?:look me up|(?:research|google|search for|look up|"
    r"find (?:public )?information (?:on|about))\s+(?:about )?(?:me|myself))\b", re.I,
)


def profile_field(directory, label):
    if not directory:
        return ""
    try:
        with (Path(directory) / "USER.md").open("rb") as profile:
            data = profile.read(8193)
    except FileNotFoundError:
        return ""
    if len(data) > 8192:
        return ""
    text = re.sub(r"<!-- ME3 remembered -->.*?<!-- /ME3 remembered -->|<!--.*?-->",
                  "", data.decode("utf-8"), flags=re.S)
    names = re.findall(r"^[ \t]*- " + re.escape(label) + r":[ \t]*(.+?)[ \t]*$", text, re.M | re.I)
    if len(names) == 1 and re.fullmatch(r"[^\W\d_]+(?:[ .’'-]+[^\W\d_]+){0,7}\.?", names[0]):
        return names[0][:100]
    return ""


def mentions_subject(text, subject):
    def words(phrase):
        tokens = re.findall(r"[^\W_]+", phrase.casefold())
        return [word[:-1] if len(word) > 4 and word.endswith("s") else word for word in tokens]
    terms = words(subject)
    if terms[:1] in (["the"], ["a"], ["an"]):
        terms = terms[1:]
    source = words(text)
    return bool(terms) and any(source[i:i + len(terms)] == terms for i in range(len(source)))


NO_SEARCH = re.compile(
    r"\b(?:do not|don['’]t|never|without)\s+(?:search|research|look|browse|googl|us(?:e|ing) Brave)", re.I,
)
CORRECTION_LEAD = re.compile(r"^(?:actually[, ]+)?(?:I (?:mean|meant)\s+)", re.I)
SITE_ACTION = re.compile(
    r"\b(?:build|create|make|design|draft|update|revise)\s+(?:me\s+)?"
    r"(?:(?:a|an|the|my|our|this)\s+)?(?:website|site|web\s*page)\b", re.I,
)
SITE_SEARCH = re.compile(
    r"^(?:please\s+)?(?:look up|search (?:online )?for|research|"
    r"check online for|find sources (?:on|for))\s+(?:the\s+)?(.+)$", re.I,
)
CURRENT = re.compile(
    r"\b(?:latest|current(?:ly)?|recent(?:ly)?|today(?:['’]s)?|news|"
    r"right now|as of (?:now|today)|this (?:week|month|year))\b", re.I,
)


def site_research(request):
    """Authorize only the public research span, never the whole site brief."""
    if not SITE_ACTION.search(request):
        return None
    clauses = re.split(r"(?<=[.!?;])\s+|\s+(?:and|then|and then)\s+", request)
    for clause in clauses:
        explicit = SITE_SEARCH.match(clause.strip())
        if not explicit:
            continue
        intent = lookup_intent("Search for " + explicit[1].rstrip(".!?"))
        if intent:
            return intent
    for clause in clauses:
        site = SITE_ACTION.search(clause)
        if not site:
            continue
        subject = re.match(r"\s+(?:about|on|covering|with)\s+(?:the\s+)?(.+)",
                           clause[site.end():], re.I)
        if subject and CURRENT.search(subject[1]):
            intent = lookup_intent("Search for " + subject[1].rstrip(".!?"))
            if intent:
                return intent
    return None


def refine_public_query(query, topic, evidence, *, source="", limit=400):
    public = set(re.findall(r"\w+", evidence[:6000].casefold()))
    used = set(re.findall(r"\w+", (query + " " + source).casefold()))
    extras = []
    for word in re.findall(r"\w+", (topic or "")[:400]):
        key = word.casefold()
        if key in public and key not in used:
            extras.append(word)
            used.add(key)
    return " ".join([query, *extras])[:limit]


def references_public_result(source, selected):
    # Remove conversational framing before checking for private/local topics.
    remaining = re.sub(r"\b(?:(?:can|could|would) you|(?:tell|show|give|walk) me)\b", "", source, flags=re.I)
    remaining, count = re.subn(
        r"\b(?:that|this|those|these|it|its|they|them|he|she|him|her|there|more|further|elaborate|expand)\b",
        "", remaining, flags=re.I,
    )
    return (selected or count > 0) and not LOCAL_CONTEXT.search(remaining)


def public_request(source, topic=None, *, one_story=None, previous_subject=None, previous_evidence=""):
    source = " ".join(source.split())
    # ASR can punctuate an abandoned question starter as a separate sentence.
    source = re.sub(r"^(?:so\s+)?(?:who|what|when|where|why|how)[.…]+\s+(?=\w)", "", source, flags=re.I)
    if NO_SEARCH.search(source):
        raise ValueError("The current request excludes a web search.")
    # When the whole turn is public, the host can ignore the model's suggested wording.
    question = re.sub(
        r"(?<=[?!\.])\s+(?:please\s+)?(?:verify|check|confirm)(?:\s+(?:it|that|this))?"
        r"\s+(?:(?:with|using|on)\s+brave|online|the official (?:site|website|source))[.!?]*$", "", source, flags=re.I,
    )
    intent = lookup_intent(question, model_selected=True)
    # A short factual follow-up may reuse the preceding successful public receipt.
    # Replace references before running the ordinary standalone/privacy checks.
    if (not intent and previous_subject and len(question) <= 140
            and re.match(r"^(?:what|which|when|where|why|how|who)\b", source, re.I)):
        rest, references = re.subn(r"\b(?:that|this|it|its|they|them|their|those|he|she|him|her|his)\b",
                                   "the subject", question, flags=re.I)
        if references and lookup_intent(rest, model_selected=True):
            # Add only model-selected words already present in public evidence.
            subject = refine_public_query(previous_subject[:200], topic, previous_evidence,
                                          source=source, limit=250)
            return f"{subject} — {question}", "answers", None
    if not intent and topic:
        topic = " ".join(topic.split()).strip()
        words = r"[\w]+(?:[.-][\w]+)*"
        supplied = set(re.findall(words, source.casefold()))
        short_query = re.fullmatch(r"[\w. -]+", topic)
        terms = re.findall(words, topic.casefold())
        grounded = short_query and terms and supplied.issuperset(terms)
        if not topic or (topic.casefold() not in source.casefold() and not grounded):
            raise ValueError("Use only the public question or search terms from this turn.")
        intent = lookup_intent(topic, model_selected=True) or lookup_intent("Search for " + topic)
    if not intent:
        raise ValueError("Ask for the public search topic in a standalone question.")
    query, _, freshness = intent
    choose_story = one_story is True or (one_story is None and NEWS_REQUEST.match(source))
    if choose_story and (not freshness or "to" not in freshness):
        period = freshness or ("pd" if re.search(r"\btoday\b", source, re.I) else "pw")
        return query, "news", period
    return intent


def resolve_request(source, topic, env, *, one_story=None, previous_subject=None, recheck_query="",
                    previous_evidence="", continuation_query="", continuation_selected=False,
                    propose_scope=None, confirmed_scope=None, scope_source="", awaiting_name=False,
                    pending_receipt=False, recent_turns=(), recent_mention="", previous_lookup=False):
    if NO_SEARCH.search(source):
        raise ValueError("The current request excludes a web search.")
    affirmative = re.fullmatch(
        r"(?:(?:yes|yeah|yep|right|correct|exactly|that's right|go ahead)(?:[, ]+please)?|"
        r"(?:(?:please|just) )?(?:search (?:for )?(?:it|that)|look (?:it|that) up)"
        r"(?: (?:please|in brief|briefly|with Brave))?)[.!]?", source.strip(), re.I,
    )
    scope = re.sub(r"^(?:do|did) you mean\s+", "", " ".join((propose_scope or "").split()),
                   flags=re.I).strip(" .?!")
    mentions = [clause for turn in recent_turns[-2:] if isinstance(turn, str) and len(turn) <= 400
                for clause in re.split(r"(?<=[.!?])\s+", turn)
                if not LOCAL_CONTEXT.search(CORRECTION_LEAD.sub("", clause)) and not re.search(
                    r"\b(?:not|never|without|don['’]t)\b", turn, re.I)]
    if (recent_mention and 1 < len(recent_mention) <= 120
            and lookup_intent("Look up " + recent_mention)
            and any(recent_mention.casefold() in clause.casefold() for clause in mentions)):
        scope = recent_mention
    if recheck_query:
        # Supplied by the host from the preceding search receipt, never from model arguments.
        query = recheck_query
        if re.search(r"\b(?:newer|later|recent|modern|latest)\b", source, re.I):
            query = "Most recent developments: " + query
        return {"query": query[:400], "mode": "web", "freshness": None, "force_live": True}
    name = CORRECTION_LEAD.sub("", source.strip()).rstrip(".!?").strip()
    name_only = re.fullmatch(r"[^\W\d_]+(?:[ '’-][^\W\d_]+){0,6}", name)
    self_name = awaiting_name and SELF_LOOKUP.match(scope_source)
    corrected_name = (previous_lookup and topic and name_only and not QUESTION.match(name)
                      and not lookup_intent(name, model_selected=True) and not references_public_result(name, False))
    if affirmative and confirmed_scope and (pending_receipt or lookup_intent(scope_source, model_selected=True)
                                           or any(mentions_subject(clause, confirmed_scope) for clause in mentions)):
        query, mode, freshness = public_request("Look up " + confirmed_scope)
        if lookup_intent(scope_source, model_selected=True) and len(scope_source) + len(query) < 390:
            query = scope_source.strip() + " — " + query
        elif pending_receipt:
            try:
                query, mode, freshness = public_request(scope_source, previous_subject=query)
            except ValueError:
                pass  # Only the confirmed public subject may leave the client.
    elif self_name or corrected_name:
        if (not name_only
                or re.match(r"(?:no|yes|stop|cancel|never|don't|skip|thanks|thank you)\b", name, re.I)
                or not lookup_intent("Look up " + name)):
            raise ValueError("The current turn did not supply a public search name.")
        query, mode, freshness = name, "web" if self_name else "answers", None
    elif SELF_LOOKUP.match(source.strip()) and not re.search(
            r"\b(?:not|never|without|don['’]t|except)\b", source, re.I):
        query = profile_field(env.get("ME3_VOICE_PROMPT_DIR"), "Public search name")
        if not query:
            return {"clarification": "What name should I search for?"}
        mode, freshness = "web", None
    elif (continuation_query and not lookup_intent(source, model_selected=True)
          and not (topic and mentions_subject(source, topic) and lookup_intent("Look up " + topic))
          and references_public_result(source, continuation_selected)):
        # Carry the authorized query. Only public evidence may supply extra
        # model-selected terms. Never send a raw conversational instruction.
        query = refine_public_query(continuation_query, topic, previous_evidence)
        mode, freshness = "answers", None
        if re.match(r"^(?:what|which|when|where|why|how|who)\b", source, re.I):
            try:
                query, mode, freshness = public_request(source, previous_subject=query)
                query = query[:400]
            except ValueError:
                pass  # The receipt alone is safe to send.
    elif scope:
        if re.search(r"\b(?:don't|don’t|do not|never|without)\b", source, re.I):
            raise ValueError("The current request excludes a web search.")
        if (len(scope) > 160 or not re.fullmatch(r"[\w ’',.()–-]+", scope)
                or not lookup_intent("Look up " + scope)):
            return {"clarification": "Which public subject do you mean?"}
        # Only the selected span may cross the boundary. Surrounding private
        # messages and the user profile stay on the client.
        in_request = mentions_subject(source, scope)
        if not in_request and not any(mentions_subject(turn, scope) for turn in mentions):
            # When both sides name a subject, a model-added year or event is
            # a hypothesis. Search the speaker's public question without it.
            names = re.findall(r"(?<=\s)[A-Z][^\W\d_]+\b", source)
            if any(mentions_subject(scope, name) for name in names):
                try:
                    return resolve_request(source, None, env, one_story=one_story)
                except ValueError:
                    pass
            return {"clarification": f"Do you mean {scope}?", "scope": scope}
        if in_request:
            try:
                query, mode, freshness = public_request(source, topic, one_story=one_story)
            except ValueError:
                # A speaker may introduce the public subject and ask about it
                # in the next sentence of the same turn.
                last = re.split(r"(?<=[.!?])\s+", source)[-1]
                if last == source:
                    raise
                query, mode, freshness = public_request(last, previous_subject=scope)
                if scope.casefold() not in query.casefold():
                    query = scope + " — " + query
        else:
            query, mode, freshness = public_request(
                source, topic, one_story=one_story, previous_subject=scope)
            if scope.casefold() not in query.casefold():
                query = scope + " — " + query
    else:
        query, mode, freshness = public_request(
            source, topic, one_story=one_story, previous_subject=previous_subject,
            previous_evidence=previous_evidence,
        )
    force_live = bool(re.search(
        r"\b(?:latest|current(?:ly)?|today|right now|news|weather|live|fresh|recheck|refresh|verify|double.check|check again|search again)\b",
        " ".join([source, query]), re.I))
    return {"query": query, "mode": mode, "freshness": freshness, "force_live": force_live}


async def fetch_evidence(query, mode, freshness, env, on_start=None):
    import httpx

    note = ""
    try:
        try:
            service = BraveLookup(lookup_token(mode, env))
            if on_start:
                on_start()
            result = await service.web_lookup(query, mode, freshness)
        except AnswersNotInPlan:
            mode = "web"
            service = BraveLookup(lookup_token(mode, env))
            result = await service.web_lookup(query, mode, freshness)
            note = "Brave Web Search · Answers unavailable on this plan.\n"
        return {"provider": "Brave", "mode": mode, "source_dates": result.source_dates,
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "brief": result.speech,
                "subject": result.subject or query,
                "sources": note + result.companion, "urls": result.urls, "support": result.support, "items": result.items}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Brave {mode} returned HTTP {exc.response.status_code}."}
    except (httpx.RequestError, TimeoutError):
        return {"error": "Brave search could not reach the provider."}
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)[:180]}


async def lookup(source, topic, env, *, on_start=None, resolve_only=False, show_results=None, **context):
    try:
        request = re.sub(r"^(?:(?:hey )?bmo[, ]+)?(?:(?:can|could|would) you )?(?:please )?",
                         "", source.strip(), flags=re.I)
        speech_only = re.search(r"\b(?:just (?:tell me|answer)|no (?:links|screen|results))\b", request, re.I)
        results = not speech_only and (show_results is True or re.match(
            r"^(?:search\b|(?:show|give) me (?:the )?(?:search )?results\b|"
            r"(?:show|give|find|gather) (?:me )?(?:some )?(?:links|sources|articles)\b)", request, re.I))
        if NO_SEARCH.search(source):
            raise ValueError("The current request excludes a web search.")
        site = site_research(request)
        if site:
            query, mode, freshness = site
            if resolve_only:
                return {"query": query, "mode": mode, "freshness": freshness,
                        "force_live": True, "site_research": True}
            return await fetch_evidence(query, mode, freshness, env, on_start)
        # A suggested topic or old receipt cannot turn a request for local work
        # into authorization to send its subject to Brave.
        if (re.match(r"^(?:draft|write|rewrite|rephrase|build|create|edit|revise|open|"
                     r"make\s+(?:me\s+)?(?:a|an|the|my|our))\b", request, re.I)
                and not re.search(r"\b(?:search (?:for|online|the web)|look up|use Brave|"
                                  r"research (?:on|about)|find (?:sources|links))\b", request, re.I)):
            raise ValueError("This is a request for Pi, not a public lookup.")
        # Display instructions stay on the client. A self-contained public
        # search can go straight to Brave without another scope negotiation.
        search = re.sub(r"(?:,|\band)\s+(?:please )?(?:show|give) me (?:the |some )?"
                        r"(?:links|results|sources)[.!?]*$", "", request, flags=re.I) if results else request
        standalone = lookup_intent(search) if results else None
        if standalone:
            query, _, freshness = standalone
            if context.get("continuation_query") and (context.get("continuation_selected") or
                                                       re.match(r"^(?:the |its |their )", query, re.I)):
                query = refine_public_query(query, topic or context.get("propose_scope") or "",
                                            context["continuation_query"] + " " + context.get("previous_evidence", ""))
            plan = {"query": query, "freshness": freshness, "force_live": True}
        else:
            plan = resolve_request(search if results else source, topic, env, **context)
        if "query" in plan:
            if results:
                plan.update(mode="web", show_results=True)
            elif (not plan["freshness"] and (speech_only or QUESTION.match(request))
                  and not context.get("awaiting_name") and not SELF_LOOKUP.match(source)):
                plan["mode"] = "answers"
        if resolve_only or "query" not in plan:
            return plan
        return await fetch_evidence(plan["query"], plan["mode"], plan["freshness"], env, on_start)
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)[:180]}


if __name__ == "__main__":
    data = json.loads(sys.stdin.read(32768))
    if data.get("op") == "fetch":
        evidence = asyncio.run(fetch_evidence(data["query"], data["mode"], data.get("freshness"), os.environ))
    else:
        evidence = asyncio.run(lookup(
            data["source"], data.get("topic"), os.environ, resolve_only=data.get("op") == "resolve", one_story=data.get("one_story"),
            show_results=data.get("show_results"), previous_subject=data.get("previous_subject"), previous_evidence=data.get("previous_evidence", ""),
            recheck_query=data.get("recheck_query") or "", continuation_query=data.get("continuation_query") or "",
            continuation_selected=data.get("continuation_selected") is True,
            propose_scope=data.get("propose_scope"), confirmed_scope=data.get("confirmed_scope"),
            scope_source=data.get("scope_source") or "", awaiting_name=data.get("awaiting_name") is True,
            pending_receipt=data.get("pending_receipt") is True, previous_lookup=data.get("previous_lookup") is True,
            recent_turns=data.get("recent_turns") or [], recent_mention=data.get("recent_mention") or "",
            on_start=lambda: print("search_started", file=sys.stderr, flush=True),
        ))
    print(json.dumps(evidence))
