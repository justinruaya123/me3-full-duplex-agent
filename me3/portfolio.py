"""Render only the owner's approved copy into a portable static page."""

import json
from html import escape
from importlib.resources import files
from string import Template
from urllib.parse import urlsplit


PORTFOLIO_PREFIX = "ME3_APPROVED_PORTFOLIO\n"


def portfolio_files(spec):
    name = spec["name"]
    facts = spec["facts"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 96:
        raise ValueError("Missing portfolio name")
    if not isinstance(facts, list) or not 1 <= len(facts) <= 3:
        raise ValueError("Select one to three portfolio facts")
    entries = []
    for fact in facts:
        url, text = fact["url"], fact["text"]
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or len(url) > 2048
                or not isinstance(text, str) or not 1 <= len(text.strip()) <= 180):
            raise ValueError("Invalid portfolio fact or source")
        entries.append(f'<li><p>{escape(text)}</p><a href="{escape(url)}">'
                       f'{escape(parsed.hostname.removeprefix("www."))} &#8599;</a></li>')
    template = files("me3").joinpath("portfolio.html").read_text(encoding="utf-8")
    html = Template(template).substitute(name=escape(name), entries="".join(entries))
    return json.dumps({"files": {"index.html": html},
                       "source_links": [fact["url"] for fact in facts]})
