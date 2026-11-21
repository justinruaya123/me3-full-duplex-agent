"""Render only the owner's approved copy into a portable static page."""

import json
from html import escape
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
    name = escape(name)
    css = """
:root { color-scheme:light; color:#192e2c; background:#f7f6ef; font-family:system-ui,sans-serif }
* { box-sizing:border-box } body { margin:0 } main { max-width:68rem; margin:auto; padding:clamp(1.4rem,6vw,5rem) }
header { padding:2rem 0 clamp(3rem,8vw,7rem); border-top:4px solid #23675a }
header p,h2 { font-size:1rem; color:#315a51; font-weight:600 }
h1 { font:normal clamp(3.4rem,10vw,8rem)/1.04 Georgia,serif; letter-spacing:-.045em; margin:1.3rem 0 0; overflow-wrap:anywhere }
section { display:grid; grid-template-columns:1fr 3fr; gap:2rem; border-top:1px solid #a7b6ac }
h2 { margin:1.9rem 0 } ul { margin:0; padding:0; list-style:none }
li { padding:1.6rem 0 1.9rem; border-bottom:1px solid #bbcac0 }
li p { font:normal clamp(1.4rem,3vw,2.25rem)/1.3 Georgia,serif; margin:0 0 1rem }
a { color:#1c5d4c; text-underline-offset:.24rem; overflow-wrap:anywhere }
a:focus-visible { outline:3px solid #18664e; outline-offset:4px }
@media(max-width:40rem) { section { display:block } h2 { margin:1.4rem 0 0 } }
"""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} · Selected work</title><style>{css}</style></head>
<body><main><header><p>Portfolio</p><h1>{name}</h1></header>
<section aria-labelledby="work"><h2 id="work">Selected work</h2>
<ul>{''.join(entries)}</ul></section></main></body></html>"""
    return json.dumps({"files": {"index.html": html},
                       "source_links": [fact["url"] for fact in facts]})
