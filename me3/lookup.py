"""Owner-requested public web lookup. Retrieved text has no action interface."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

BASE = "https://api.search.brave.com/res/v1"
WINDOW = re.compile(r"(\d{4}-\d\d-\d\d)\s*(?:to|through|and)\s*(\d{4}-\d\d-\d\d)", re.I)
PERIODS = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
EXPLICIT = re.compile(r"^(?:/lookup|look up|search(?: the web)?(?: for)?)\s+", re.I)
CURRENT = re.compile(
    r"\b(?:latest|currently|current|today|yesterday|recent|right now|forecast|news|price|weather)\b",
    re.I,
)


CALENDAR_WINDOW = re.compile(
    r"\b(?:from|between|since|after|before|on)\s+(?:\d{1,4}[-/]|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d)",
    re.I,
)


def lookup_intent(text: str):
    query, explicit = EXPLICIT.subn("", text.strip(), count=1)
    question = re.match(
        r"^(what|when|who|where|how|which|is|are|does|did|has|have|tell me|give me|show me)\b",
        query,
        re.I,
    )
    temporal = (
        CURRENT.search(query) or WINDOW.search(query) or CALENDAR_WINDOW.search(query)
    )
    if not explicit and (
        not question
        or not temporal
        or re.search(r"\b(my|our|your|job|task|project|profile)\b", query, re.I)
    ):
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
    return query.strip(), "answers", None


def speech_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]*>|https?://\S+|www\.\S+", "", value, flags=re.I)
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:650]


@dataclass(frozen=True)
class LookupResult:
    speech: str
    companion: str


def source(record: dict):
    url = record.get("url")
    if not isinstance(url, str) or len(url) > 2048 or not url.isprintable():
        raise ValueError("Invalid citation URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Invalid citation source")
    host = parsed.hostname.removeprefix("www.")
    title = speech_text(str(record.get("title") or host))
    snippet = speech_text(str(record.get("snippet") or record.get("description") or ""))
    published = speech_text(str(record.get("page_age") or record.get("age") or ""))
    return title, host, snippet, url, published


def result(records: list, answer: str, cached: bool) -> LookupResult:
    lines, spoken = [], []
    for record in records[:5]:
        title, host, snippet, url, published = source(record)
        start, end = record.get("start_index"), record.get("end_index")
        claim = ""
        if type(start) is int and type(end) is int and 0 <= start < end <= len(answer):
            claim = speech_text(answer[start:end])
        # Preserve provenance by speaking the excerpt when a generated claim
        # cannot be matched to the cited source text.
        supported = claim if claim and claim.casefold() in snippet.casefold() else snippet
        if supported and len(spoken) < 2:
            spoken.append("According to " + host + ", " + supported[:350])
        lines.append(f"{title} {url}" + (f" ({published})" if published else ""))
        if supported:
            lines.append(supported)
    if not spoken:
        raise ValueError("No supporting source excerpts")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = "Cached web result. " if cached else ""
    return LookupResult(
        label + " ".join(spoken),
        "\n".join([label + "Retrieved " + stamp, *lines]),
    )


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
                    "messages": [{"role": "user", "content": query}],
                },
            ) as response:
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
                    speech_text(answer),
                    response.headers.get("Age", "0") != "0",
                )
        if mode != "web" or not freshness:
            raise ValueError("Invalid search mode or freshness")
        if freshness not in PERIODS.values():
            match = WINDOW.fullmatch(freshness)
            if (
                not match
                or freshness != match[1] + "to" + match[2]
                or date.fromisoformat(match[1]) > date.fromisoformat(match[2])
            ):
                raise ValueError("Invalid search date window")
        async with client.stream(
            "GET",
            BASE + "/web/search",
            params={"q": query, "freshness": freshness, "count": 5},
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
