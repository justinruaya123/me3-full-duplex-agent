"""Exercise the real loopback window with synthetic snapshots and a temporary PTY.

Run from the installed checkout with python -m integrations.voicechat.check_readable.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, expect

from integrations.voicechat import window


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        shots = window.LOCAL / "theme-preview"
        shots.mkdir(parents=True, exist_ok=True)
        window.LOCAL = directory
        window.face_manifest = lambda: {s: [] for s in window.STATES}
        ready = asyncio.get_running_loop().create_future()
        window.open_window = lambda url, profile: ready.set_result(url)

        def panel(name, data):
            path = directory / (name + ".tmp")
            path.write_text(json.dumps(data))
            path.replace(directory / (name + ".json"))

        with (directory / "lock").open("w+") as lock:
            server = asyncio.create_task(window.serve(["/bin/cat"], directory, lock))
            try:
                done, _ = await asyncio.wait(
                    [ready, server], timeout=5, return_when=asyncio.FIRST_COMPLETED
                )
                if server in done:
                    await server
                url = ready.result()
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch()
                    page = await browser.new_page(
                        viewport={"width": 800, "height": 600}, reduced_motion="reduce"
                    )
                    errors = []
                    external = []
                    page.on("pageerror", lambda err: errors.append(str(err)))
                    page.on(
                        "request",
                        lambda req: (
                            external.append(req.url)
                            if req.url.startswith("http")
                            and not req.url.startswith(url)
                            else None
                        ),
                    )
                    await page.goto(url)

                    async def check(id, text):
                        await expect(page.locator("#" + id)).to_have_text(text)

                    async def shot(name):
                        await page.screenshot(path=str(shots / (name + ".png")))

                    async def no_overflow():
                        assert await page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth && [...document.querySelectorAll('main, #workspace, header, #board')].filter(n=>n.clientWidth).every(n=>n.scrollWidth<=n.clientWidth+1)"
                        )

                    await expect(page.locator("#duplex")).to_be_enabled()
                    await page.locator("#appearance-home").click()
                    await page.locator("#theme-choice").select_option("bmo-readable")
                    await page.locator("#pref-done").click()
                    await check("activity", "Idle")
                    assert await page.locator("#face-stage").bounding_box() == {
                        "x": 0, "y": 0, "width": 800, "height": 600,
                    }
                    assert await page.evaluate(
                        """async () => (await document.fonts.load('20px "Atkinson Hyperlegible Next"')).length>0"""
                    )
                    await shot("presence")
                    v = {
                        "mic": "on",
                        "wakePhrase": "Hey Beemo",
                        "asr": "Compare the two meeting times for Friday.",
                        "output": "",
                        "listening": True,
                    }
                    panel("voice", v)
                    await check("activity", "Listening")
                    await shot("listening")
                    v.update(
                        listening=False,
                        speaking=True,
                        output="Friday at ten works for both people.",
                    )
                    panel("voice", v)
                    await check("activity", "Speaking")
                    await shot("speaking")
                    job = {
                        "id": "a",
                        "kind": "draft",
                        "agent": "Planner",
                        "revision": 1,
                        "status": "running",
                        "text": "Checking the two meeting windows.",
                    }
                    panel("agents", [job])
                    await check("ready-count", "1 working")
                    await page.locator("#ready-count").click()
                    await check("job-output", job["text"])
                    await shot("work")
                    await page.locator("#close").click()
                    panel("voice", {**v, "speaking": False})
                    panel("agents", [{**job, "status": "completed"}])
                    await check("ready-count", "1 result ready")
                    await check("activity", "Idle")
                    await shot("ready")
                    panel("voice", {**v, "mic": "error", "speaking": False})
                    await check("activity", "Error")
                    await shot("error")
                    panel(
                        "canvas",
                        {
                            "board": {
                                "title": "Friday options",
                                "rows": [
                                    {
                                        "kind": "note",
                                        "label": "Ten o'clock",
                                        "detail": "Room 105",
                                    }
                                ],
                            },
                            "done": True,
                        },
                    )
                    panel("focus", {"panel": "canvas", "request": "original"})
                    await page.get_by_text("Room 105").wait_for()
                    panel("canvas", {"board": {"rows": 4}, "done": True})
                    await page.get_by_text(
                        "The latest view could not be displayed."
                    ).wait_for()
                    await page.get_by_text("Room 105").wait_for()
                    process = await asyncio.create_subprocess_exec(
                        "node",
                        "--input-type=module",
                        "-e",
                        'import {loadRenderer} from "./integrations/voicechat/preview.mjs";console.log((await loadRenderer())("<h1>Schedule</h1><p>Friday at ten</p>"));',
                        stdout=asyncio.subprocess.PIPE,
                    )
                    html = (await process.communicate())[0].decode()
                    panel("canvas", {"html": html, "done": True})
                    frame = page.frame_locator("iframe")
                    await frame.get_by_text("Friday at ten").wait_for()
                    face_box = await page.locator("#close #face-stage").bounding_box()
                    canvas_box = await page.locator("iframe").bounding_box()
                    assert face_box["width"] <= 80 and face_box["x"] > 700
                    assert face_box["y"] + face_box["height"] <= canvas_box["y"]
                    assert await frame.locator("body").evaluate(
                        "el=>getComputedStyle(el).fontFamily.includes('Atkinson')"
                    )
                    await page.locator("#console").click()
                    await expect(page.locator(".xterm-screen")).to_be_visible()
                    await page.locator("#close").click()
                    panel("voice", {**v, "speaking": False})
                    await page.locator("#appearance-home").click()
                    await page.locator("#large-text").check()
                    await page.locator("#still-face").check()
                    await page.locator("#pref-spacing").select_option("wide")
                    await page.locator("#pref-background").select_option("mint")
                    await page.locator("#pref-font").select_option("system")
                    await page.locator("#pref-done").click()
                    await page.reload()
                    await expect(page.locator("#duplex")).to_be_enabled()
                    await check("activity", "Idle")
                    assert await page.evaluate(
                        "getComputedStyle(document.documentElement).fontFamily.includes('system-ui')"
                    )
                    await shot("large")
                    await page.locator("#appearance-home").click()
                    assert await page.locator("#still-face").is_checked()
                    assert await page.locator("#pref-spacing").input_value() == "wide"
                    await page.locator("#pref-done").click()
                    panel(
                        "voice",
                        {
                            **v,
                            "asr": "Long caption " * 50,
                            "output": "A" * 500,
                            "speaking": False,
                        },
                    )
                    # Simulate the reduced CSS viewport of zoom and text-spacing overrides.
                    await page.add_style_tag(
                        content="p, label, #asr, #output {line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}p{margin-bottom:2em!important}"
                    )
                    for w, h in ((800, 480), (400, 300), (320, 568)):
                        await page.set_viewport_size({"width": w, "height": h})
                        await no_overflow()
                        await page.locator("#inspect").click()
                        await page.locator("#agents").click()
                        await no_overflow()
                        await page.locator("#close").click()
                    await page.locator("#appearance-home").click()
                    await page.locator("#pref-font").select_option("default")
                    await page.locator("#pref-done").click()
                    await page.route("**/*.ttf", lambda route: route.abort())
                    await page.reload()
                    await expect(page.locator("#duplex")).to_be_enabled()
                    await expect(page.locator("#asr")).to_be_visible()
                    await page.locator("#appearance-home").click()
                    await page.locator("#pref-reset").click()
                    await page.locator("#pref-done").click()
                    assert (
                        await page.locator("html").get_attribute("data-theme")
                        == "classic"
                    )
                    assert not errors, errors
                    assert not external, external
                    await browser.close()
                    print(
                        "PASS classic/opt-in, 7 snapshots, 4 viewport sizes, real local renderer and xterm, font load, invalid board retention, persisted reading settings and reset. Zero external HTTP requests and page errors."
                    )
            finally:
                server.cancel()
                await asyncio.gather(server, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
