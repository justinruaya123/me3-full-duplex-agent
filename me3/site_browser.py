"""Render generated bundles in a fresh Chromium profile with offline routing."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import tempfile
from urllib.parse import unquote, urlsplit

ORIGIN = "https://me3-site.invalid"
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}
NAVIGATION_LABELS = (
    "Home",
    "About me",
    "About",
    "Bio",
    "Contact",
    "Projects",
    "Portfolio",
    "Work",
    "Menu",
    "Open menu",
    "Close menu",
    "Back",
    "Next",
    "Previous",
    "Back to top",
    "Skip to content",
    "Read more",
    "Email",
    "Phone",
)
CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'none'; "
    "frame-src 'none'; worker-src 'none'; form-action 'none'; "
    "object-src 'none'; base-uri 'none'; sandbox allow-scripts"
)


async def verify_browser(
    files: dict[str, str],
    required: list[str],
    personal_keys: list[str] | None,
    source_links=(),
) -> dict:
    try:
        from playwright.async_api import Error, async_playwright
    except ImportError as exc:
        raise ValueError("Website browser verification requires Playwright") from exc

    try:
        async with asyncio.timeout(45), async_playwright() as playwright:
            with tempfile.TemporaryDirectory(prefix="me3-site-") as home:
                browser = await playwright.chromium.launch(
                    chromium_sandbox=True,
                    headless=True,
                    env={"HOME": home, "TMPDIR": home, "PATH": os.defpath},
                    args=[
                        "--disable-background-networking",
                        "--host-resolver-rules=MAP * ~NOTFOUND",
                        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    ],
                )
                try:
                    for width, height in VIEWPORTS.values():
                        ctx = await browser.new_context(
                            viewport={"width": width, "height": height},
                            offline=True,
                            accept_downloads=False,
                        )
                        try:
                            await check_viewport(ctx, files, required, personal_keys, source_links)
                        finally:
                            await ctx.close()
                    return {
                        "engine": "chromium",
                        "version": browser.version,
                        "viewports": list(VIEWPORTS),
                        "network": "offline",
                        "required_fields": len(required),
                    }
                finally:
                    await browser.close()
    except (Error, TimeoutError) as exc:
        raise ValueError("Website browser could not complete verification") from exc


async def check_viewport(ctx, files, required, personal_keys, source_links):
    errors = set()

    async def serve(route):
        url = urlsplit(route.request.url)
        name = unquote(url.path).lstrip("/") or "index.html"
        if (
            url.scheme + "://" + url.netloc != ORIGIN
            or route.request.method != "GET"
            or name not in files
        ):
            errors.add("blocked request")
            await route.abort()
            return
        await route.fulfill(
            body=files[name],
            status=200,
            content_type=mimetypes.guess_type(name)[0] or "text/plain",
            headers={
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def deny_socket(socket):
        errors.add("blocked socket")
        await socket.close()

    await ctx.route("**/*", serve)
    await ctx.route_web_socket("**/*", deny_socket)
    page = await ctx.new_page()
    ctx.on("page", lambda _: errors.add("unexpected window"))
    page.on("pageerror", lambda _: errors.add("page exception"))
    page.on(
        "console",
        lambda msg: errors.add("console error") if msg.type == "error" else None,
    )
    page.on("requestfailed", lambda _: errors.add("failed request"))
    anchors, links, visible = {}, [], []
    for name in files:
        if not name.lower().endswith(".html"):
            continue
        await page.goto(f"{ORIGIN}/{name}", wait_until="networkidle", timeout=6000)
        # Raw layout/DOM facts only. Never turn generated labels into commands.
        if await page.locator("html").evaluate(
            "(el) => el.scrollWidth > window.innerWidth + 1"
        ):
            errors.add("horizontal overflow")
        content = await page.locator("body").inner_text(timeout=2000)
        if not content.strip():
            errors.add("empty page")
        visible.append(" ".join(content.split()).casefold())
        anchors[name] = await page.locator("[id],a[name]").evaluate_all(
            "els => els.flatMap(el => [el.id, el.getAttribute('name')]).filter(Boolean)"
        )
        hrefs = await page.locator("a[href]").evaluate_all(
            "els => els.map(el => el.href)"
        )
        links.extend((name, index, href) for index, href in enumerate(hrefs))
        if len(links) > 128:
            errors.add("link limit")
            break
    for source_page, index, href in links:
        url = urlsplit(href)
        if href in source_links and url.scheme in {"http", "https"} and url.netloc != urlsplit(ORIGIN).netloc:
            continue  # Approved source citation. Never navigate off the local origin.
        name = unquote(url.path).lstrip("/") or "index.html"
        if (
            url.scheme + "://" + url.netloc != ORIGIN
            or name not in files
            or (url.fragment and unquote(url.fragment) not in anchors.get(name, []))
        ):
            errors.add("broken or external link")
            continue
        if errors:
            break
        await page.goto(f"{ORIGIN}/{source_page}", wait_until="load", timeout=5000)
        link = page.locator("a[href]").nth(index)
        if await link.is_visible():
            await link.click(timeout=1500)
            await page.wait_for_url(
                lambda actual: actual == href, timeout=1500, wait_until="commit"
            )
    if errors:
        raise ValueError("Website browser check failed: " + ", ".join(sorted(errors)))
    for value in required:
        if not any(
            " ".join(value.split()).casefold() in page_text for page_text in visible
        ):
            raise ValueError("Website is missing approved content")
    if personal_keys is not None:
        phrases = sorted(
            [*NAVIGATION_LABELS, *personal_keys, *required], key=len, reverse=True
        )
        allowed = re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(" ".join(p.split())) for p in phrases)
            + r")(?!\w)",
            re.I,
        )
        if any(re.search(r"\w", allowed.sub("", text)) for text in visible):
            raise ValueError("Personal website contains unapproved visible copy")
