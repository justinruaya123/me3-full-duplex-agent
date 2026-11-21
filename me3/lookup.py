"""Owner-requested public web lookup. Retrieved text has no action interface."""

from __future__ import annotations

import html
import json
import random
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

BASE = "https://api.search.brave.com/res/v1"
WINDOW = re.compile(r"(\d{4}-\d\d-\d\d)\s*(?:to|through|and)\s*(\d{4}-\d\d-\d\d)", re.I)
PERIODS = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
EXPLICIT = re.compile(
    r"^(?:/lookup|look up|search(?: (?:the )?(?:web|internet|online))?(?: for)?|"
    r"(?:do|run) (?:a |an )?(?:web|internet|online) search(?: for| on)?|"
    r"(?:do (?:some |a )?)?research(?: on| into)?|"
    r"(?:find|gather|show me|give me) (?:some )?(?:sources|papers|studies|articles|links)"
    r"(?: on| about| for)?|look into)\s+",
    re.I,
)
QUESTION = re.compile(
    r"^(?:what(?! about)|when|who|why|where|how|which|is|are|was|were|do|does|did|"
    r"has|have|can|could|will|would)\b\S*\s+\w", re.I,
)
SEARCH_TOPIC = re.compile(
    r"\b(?:news|headlines|latest updates|latest on|research|studies|papers|sources|articles)\b",
    re.I,
)
FACT_REQUEST = re.compile(
    r"^(?:(?:a |an |some )?(?:(?:random|interesting|fun|surprising|quick) )?facts?\b|"
    r"something (?:interesting|surprising|new|fun)\b)", re.I,
)
TOPICAL_REQUEST = re.compile(
    r"^(?:any |the |today['’]s )?(?:latest |current )?"
    r"(?:weather|forecast|news|headlines|updates)\b|^latest\s+\w+\s+news\b", re.I,
)
# Short spoken requests often omit a question verb ("Any recent science news?").
NEWS_REQUEST = re.compile(
    r"^(?:any |some |(?:the )?(?:recent |latest |current |today['’]s ))"
    r"(?:[\w'-]+ ){0,5}(?:news|headline)[?.!]*$|"
    r"^(?:any |some |the )?(?:recent |latest |current |today['’]s )?news (?:from|in|about|on)\b",
    re.I,
)
# A question that needs local/private context stays with the foreground.
LOCAL_CONTEXT = re.compile(
    r"\b(?:i|me|my|mine|our|ours|we|you|your|yours|it|its|that|this|these|those|"
    r"they|them|he|she|here|earlier|above|previous|again|private|personal|"
    r"passwords?|credentials?|secrets?|api keys?|tokens?|profile|memory|"
    r"files?|folders?|workspace|repo(?:sitory)?|prototypes?|branch(?:es)?|"
    r"commits?|merge|patch|the build|the result|"
    r"jobs?|tasks?|projects?|meetings?|chats?|conversation|draft|notes?)\b|"
    r"[/\\`@]|\b\w+(?:\.| dot )(?:txt|md|py|js|json|html|pdf|csv|docx|xlsx)\b|"
    r"\b(?:do not|don['’]t|without) (?:search|look|browse|use)\b|"
    r"^(?:what(?:['’]s| is) (?:up|new|happening|going on)|how (?:was|is) "
    r"(?:lunch|dinner|work|everything|life))\s*[.?!]*$",
    re.I,
)
ARITHMETIC = re.compile(
    r"\b(?:plus|minus|times|divided by|multiplied by)\b|\d\s*[+*/-]\s*\d", re.I,
)


CALENDAR_WINDOW = re.compile(
    r"\b(?:from|between|since|after|before|on)\s+(?:\d{1,4}[-/]|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d)",
    re.I,
)


def lookup_intent(
    text: str, *, model_selected: bool = False
) -> tuple[str, str, str | None] | None:
    """Select an endpoint using only the owner's committed, standalone request."""
    if (len(text) > 400 or not text.strip().isprintable()
            or re.search(r"[?!;]\s*\S|(?<=[a-z])\.\s+\w", text)):
        return None
    request = re.sub(
        r"^(?:please\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?",
        "", text.strip(), count=1, flags=re.I,
    )
    query, explicit = EXPLICIT.subn("", request, count=1)
    if not explicit:
        query = re.sub(r"^(?:tell me|give me|show me)\s+", "", query, flags=re.I)
    # Ignore the separators inside date expressions when checking for local paths.
    scope = re.sub(r"(?<=\d)/(?=\d)", "-", query)
    if not query.strip() or LOCAL_CONTEXT.search(scope):
        return None
    if not explicit and ARITHMETIC.search(query) and not CALENDAR_WINDOW.search(query):
        return None
    description = model_selected and re.match(
        r"^(?:explain|describe|about|define)\s+\w", query, re.I,
    )
    fact_request = request != query and FACT_REQUEST.match(query)
    if not (explicit or QUESTION.match(query) or TOPICAL_REQUEST.match(query)
            or NEWS_REQUEST.match(query) or fact_request or description):
        return None
    match = WINDOW.search(query)
    if match:
        start, end = match.groups()
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("The start date must come before the end date.")
        query = (
            re.sub(r"\b(?:from|between)\s*$", "", query[: match.start()], flags=re.I)
            + query[match.end() :]
        )
        return query.strip(" ?.,"), "web", start + "to" + end
    if CALENDAR_WINDOW.search(query):
        raise ValueError("Please give the date window as YYYY-MM-DD to YYYY-MM-DD.")
    period = re.search(
        r"\b(?:in |over |during )?(?:the )?(?:past|last) (day|week|month|year)\b",
        query,
        re.I,
    )
    if period:
        return query.strip(), "web", PERIODS[period[1].lower()]
    search_command = explicit and not re.match(r"^(?:/lookup|look up)\b", request, re.I)
    mode = "web" if SEARCH_TOPIC.search(query) or search_command else "answers"
    return query.strip(), mode, None


def speech_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]*>|https?://\S+|www\.\S+", "", value, flags=re.I)
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:650]


@dataclass(frozen=True)
class LookupResult:
    speech: str
    companion: str
    urls: tuple[str, ...] = ()
    support: str = ""
    subject: str = ""
    source_dates: tuple[dict, ...] = ()

    def terminal_text(self, mode: str) -> str:
        sources = self.companion
        if mode == "answers" and self.urls:
            sources = "Sources\n" + "\n".join(self.urls)
        return self.speech + "\n\n" + sources


def source(record: dict):
    if not isinstance(record, dict):
        raise ValueError("Invalid citation record")
    url = record.get("url")
    if (not isinstance(url, str) or len(url) > 2048 or not url.isprintable()
            or re.search(r"[\s\\<>]", url)):
        raise ValueError("Invalid citation URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid citation source")
    host = parsed.hostname.removeprefix("www.")
    title = speech_text(str(record.get("title") or host))
    excerpt = record.get("snippet") or record.get("description") or ""
    if not isinstance(excerpt, str):
        raise ValueError("Invalid citation excerpt")
    snippet = speech_text(excerpt)
    published = speech_text(str(record.get("page_age") or record.get("age") or ""))
    return title, host, snippet, url, published


def result(records: list, answer: str, cached: bool) -> LookupResult:
    lines, excerpts, spans, urls, support = [], [], [], [], []
    dates = []
    for record in records[:5]:
        title, host, snippet, url, published = source(record)
        if not snippet:
            continue
        start, end = record.get("start_index"), record.get("end_index")
        if type(start) is int and type(end) is int and 0 <= start < end <= len(answer):
            spans.append((start, end))
        excerpts.append("According to " + host + ", " + snippet[:350])
        lines.append(f"{title} {url}" + (f" ({published})" if published else ""))
        lines.append(snippet)
        support.extend([title, snippet])
        extra = record.get("extra_snippets")
        if isinstance(extra, list):
            for value in extra[:3]:
                if isinstance(value, str) and (detail := speech_text(value)) and detail != snippet:
                    lines.append(detail)
                    support.append(detail)
        if url not in urls:
            urls.append(url)
            # Preserve the provider's date separately from its relative age label.
            date_value = record.get("published_at")
            dates.append({"url": url, "published_at": speech_text(str(date_value)) if date_value else None,
                          "page_date": speech_text(str(record["page_age"])) if record.get("page_age") else None,
                          "reported_age": speech_text(str(record["age"])) if record.get("age") else None})
    if not excerpts:
        raise ValueError("No supporting source excerpts")
    # Brave indexes its original answer, before whitespace or speech cleanup.
    # Cite only that text. Merge overlapping citations to avoid repeating claims.
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and not answer[merged[-1][1]:start].strip():
            merged[-1] = merged[-1][0], max(merged[-1][1], end)
        else:
            merged.append((start, end))
    paragraphs = [
        clean for start, end in merged
        for part in re.split(r"\n\s*\n", answer[start:end])
        if (clean := speech_text(part))
    ]
    spoken = "\n\n".join((paragraphs or excerpts)[:2])
    if len(spoken) > 650:
        bounded = spoken[:650]
        ends = list(re.finditer(r"[.!?](?=\s|$)", bounded))
        spoken = bounded[:ends[-1].end()] if ends else bounded.rsplit(" ", 1)[0] + "…"
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = "Cached web result. " if cached else ""
    return LookupResult(
        label + spoken,
        "\n".join([label + "Retrieved " + stamp, *lines]),
        tuple(urls),
        "\n".join([*paragraphs, *support]),
        source_dates=tuple(dates),
    )


def one_news_story(records, freshness, cached):
    """Keep just one dated article and its evidence for the spoken summary."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days={"pd": 1, "pw": 7, "pm": 31, "py": 365}[freshness])
    stories = {}
    for record in records[:8]:
        try:
            title, _, snippet, url, _ = source(record)
            stamp = datetime.fromisoformat(record.get("page_age") or "")
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if record.get("title") and title and snippet and cutoff <= stamp <= now and urlsplit(url).path.strip("/"):
            stories[url] = record
    if not stories:
        raise ValueError("Brave found no dated news story in the requested period.")
    chosen = random.choice(list(stories.values()))
    return replace(result([chosen], "", cached), subject=speech_text(chosen["title"])[:200])


def lookup_token(mode: str, env) -> str:
    if mode == "answers" and env.get("BRAVE_ANSWERS_API_KEY"):
        return env["BRAVE_ANSWERS_API_KEY"]
    return env.get("BRAVE_SEARCH_API_KEY", "")


class AnswersNotInPlan(Exception):
    """Brave explicitly declined the requested Answers option for this plan."""


class BraveLookup:
    def __init__(self, token: str, *, client=None):
        if not token:
            raise ValueError("Set BRAVE_SEARCH_API_KEY to enable lookup")
        self.token, self.client = token, client

    async def web_lookup(self, query: str, mode: str, freshness: str | None):
        import httpx

        if not query.strip() or len(query) > 400:
            raise ValueError("Search requires a query of 1 to 400 characters")
        if self.client is None:
            async with httpx.AsyncClient(timeout=20) as client:
                return await self._request(client, query, mode, freshness)
        return await self._request(self.client, query, mode, freshness)

    async def _request(self, client, query, mode, freshness):
        if mode == "answers" and freshness is None:
            async with client.stream(
                "POST",
                BASE + "/chat/completions",
                headers={"Authorization": "Bearer " + self.token},
                json={
                    "model": "brave",
                    "stream": True,
                    "enable_citations": True,
                    "enable_research": False,
                    "messages": [{"role": "user", "content": (
                        "Give a spoken answer in one short sentence, preferably under 25 words. "
                        "Keep essential caveats. Use plain words for symbols and math. "
                        "Cite factual statements using the citation metadata.\n\n" + query
                    )}],
                },
            ) as response:
                if response.status_code in {400, 403}:
                    try:
                        detail = json.loads(await bounded_body(response))
                    except ValueError:
                        detail = {}
                    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
                        if detail["error"].get("code") == "OPTION_NOT_IN_PLAN":
                            raise AnswersNotInPlan()
                response.raise_for_status()
                data = await bounded_body(response)
                body = ""
                done = False
                for line in data.decode().splitlines():
                    if not line.startswith("data:"):
                        continue
                    item = line[5:].strip()
                    if item == "[DONE]":
                        done = True
                        break
                    event = json.loads(item)
                    if "error" in event:
                        raise ValueError("Lookup provider reported an error")
                    for choice in event.get("choices", []):
                        body += choice["delta"].get("content") or ""
                if not done:
                    raise ValueError("Incomplete search stream")
                citations = []

                def control(match):
                    value = json.loads(match[2])
                    if match[1] == "citation":
                        citations.append(value)
                    return ""

                answer = re.sub(
                    r"<(citation|usage)>(.*?)</\1>", control, body, flags=re.S
                )
                if "<citation" in answer or "<usage" in answer:
                    raise ValueError("Incomplete citation")
                return result(
                    citations,
                    answer,
                    response.headers.get("Age", "0") != "0",
                )
        if mode == "news" and freshness in PERIODS.values():
            async with client.stream(
                "GET", BASE + "/news/search",
                params={"q": query, "freshness": freshness, "count": 8, "country": "ALL"},
                headers={"X-Subscription-Token": self.token},
            ) as response:
                response.raise_for_status()
                records = json.loads(await bounded_body(response)).get("results") or []
                return one_news_story(records, freshness, response.headers.get("Age", "0") != "0")
        if mode != "web":
            raise ValueError("Invalid search mode or freshness")
        if freshness is not None and freshness not in PERIODS.values():
            match = WINDOW.fullmatch(freshness)
            if (
                not match
                or freshness != match[1] + "to" + match[2]
                or date.fromisoformat(match[1]) > date.fromisoformat(match[2])
            ):
                raise ValueError("Invalid search date window")
        params = {"q": query, "count": 5, "extra_snippets": "true"}
        if freshness is not None:
            params["freshness"] = freshness
        async with client.stream(
            "GET",
            BASE + "/web/search",
            params=params,
            headers={"X-Subscription-Token": self.token},
        ) as response:
            response.raise_for_status()
            records = json.loads(await bounded_body(response))["web"]["results"]
            return result(records, "", response.headers.get("Age", "0") != "0")


async def bounded_body(response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=8192):
        if len(body) + len(chunk) > 256 * 1024:
            raise ValueError("Search response exceeds limit")
        body.extend(chunk)
    return bytes(body)
