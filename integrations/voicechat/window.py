"""One local window around the project's real Pi TUI, with read-only side panels."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import re
import pty
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import webbrowser

from aiohttp import WSMsgType, web

from .theme.appearance import appearance, read_appearance, TOKENS

HERE = Path(__file__).resolve().parent
LOCAL = HERE.parents[1] / ".local"
ASSETS = LOCAL / "openintelligentui-renderer/node_modules/@xterm"
FILES = {"": HERE / "window.html", "face.mjs": HERE / "face.mjs", "window.js": HERE / "window.js",
         "window.css": HERE / "window.css", "xterm.js": ASSETS / "xterm/lib/xterm.js",
         "fit.js": ASSETS / "addon-fit/lib/addon-fit.js", "xterm.css": ASSETS / "xterm/css/xterm.css"}
THEME = HERE / "theme"
FILES.update({name: THEME / name for name in ("readable.css", "display.mjs", "design.tokens.json")})
FILES.update({p.name: p for p in (THEME / "fonts").glob("*.ttf")})
STATES = {"idle": 1, "warmup": 1, "speaking": 3, "thinking": 4,
          "listening": 2, "capturing": 1, "error": 1}


def website_download(name, folder, chats):
    match = re.fullmatch(r"website-([a-f0-9]{32})-([1-9][0-9]*)\.zip", name)
    if not match:
        return None
    try:
        jobs = json.loads((folder / "agents.json").read_bytes())
    except FileNotFoundError:
        return None
    for job in jobs:
        if (job.get("id") != match[1] or str(job.get("revision")) != match[2]
                or job.get("kind") != "website" or job.get("status") != "completed"):
            continue
        archive = Path(job.get("archive") or "")
        if not archive.is_absolute() or not archive.is_relative_to(chats):
            continue
        relative = archive.relative_to(chats)
        if (relative.parts[1:] == ("jobs", match[1], "revision-" + match[2], "website.zip")
                and archive.resolve() == chats.resolve() / relative and archive.is_file()):
            return archive
    return None


def face_manifest():
    result = {}
    for state, count in STATES.items():
        frames = []
        for i in range(1, count + 1):
            path = HERE / "faces" / f"{state}-{i}.png"
            if not path.is_file():
                continue
            with path.open("rb") as file:
                header = file.read(24)
            if (len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR"
                    and struct.unpack(">II", header[16:24]) == (800, 480)):
                frames.append(path.name)
        result[state] = frames
    return result



def open_window(url, profile):
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    browser = str(chrome) if sys.platform == "darwin" and chrome.is_file() else (
        shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    )
    if browser:
        subprocess.Popen([browser, "--kiosk", "--start-fullscreen", "--app=" + url, "--user-data-dir=" + str(profile),
                          "--no-first-run", "--no-default-browser-check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    elif not webbrowser.open(url):
        print("Open the Pi window at " + url, flush=True)


async def serve(argv, folder, lock):
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host = "127.0.0.1:" + str(sock.getsockname()[1])
    origin = "http://" + host
    prefix = "/" + secrets.token_urlsafe(24) + "/"
    url = origin + prefix
    master, slave = pty.openpty()
    os.set_blocking(master, False)
    assets = face_manifest()
    images = {name: HERE / "faces" / name for group in assets.values() for name in group}
    prefs_path = LOCAL / "window-appearance.json"
    child = None
    connected = False
    idle = None
    history = bytearray()
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
               "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
               "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
               "style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'self'; "
               "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}

    async def handle(req):
        nonlocal child, connected, idle
        if req.host != host:
            raise web.HTTPNotFound()
        name = req.match_info.get("name", "")
        if name.startswith("website-"):
            archive = website_download(name, folder, LOCAL / "voice-worker/chats")
            if archive is None:
                raise web.HTTPNotFound()
            return web.FileResponse(archive, headers={**headers, "Content-Type": "application/zip",
                                    "Content-Disposition": 'attachment; filename="website.zip"'})
        if name == "display.json":
            return web.json_response({"appearance": read_appearance(prefs_path), "faces": assets,
                                      "tokens": TOKENS}, headers=headers)
        if name in images:
            return web.FileResponse(images[name], headers={**headers, "Cache-Control": "private, max-age=86400"})
        if name in FILES:
            return web.FileResponse(FILES[name], headers={**headers, "Access-Control-Allow-Origin": "*"}
                                    if name.endswith(".ttf") else headers)
        if name != "stream" or req.headers.get("Origin") != origin or connected:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(max_msg_size=16384, heartbeat=10)
        await ws.prepare(req)
        connected = True
        idle.cancel()
        async def output():
            nonlocal child
            versions = {}
            if history:
                await ws.send_bytes(bytes(history))
            while True:
                try:
                    chunk = os.read(master, 32768)
                except BlockingIOError:
                    chunk = None
                except OSError:
                    chunk = b""
                if chunk == b"" or (child and child.poll() is not None):
                    stopped.set()
                    return
                if chunk:
                    history.extend(chunk)
                    del history[:-65536]
                    await ws.send_bytes(chunk)
                for panel in ("voice", "canvas", "agents", "focus"):
                    path = folder / (panel + ".json")
                    try:
                        version = path.stat().st_mtime_ns
                        if versions.get(panel) != version:
                            await ws.send_json({"panel": panel, "version": str(version),
                                                "data": json.loads(path.read_bytes())})
                            versions[panel] = version
                    except FileNotFoundError:
                        pass
                await asyncio.sleep(.03 if chunk else .08)

        writer = asyncio.create_task(output())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY and child:
                    # Small bounded keyboard/paste frames, retry if the PTY is full.
                    data = memoryview(msg.data)
                    while data:
                        try:
                            data = data[os.write(master, data):]
                        except BlockingIOError:
                            await asyncio.sleep(.01)
                elif msg.type == WSMsgType.TEXT:
                    size = json.loads(msg.data)
                    if isinstance(size, dict) and "appearance" in size:
                        try:
                            prefs = appearance(size["appearance"])
                            temp = prefs_path.with_suffix(".tmp")
                            temp.write_text(json.dumps(prefs))
                            temp.replace(prefs_path)
                        except (ValueError, OSError):
                            await ws.send_json({"panel": "preference_error", "data": "Could not save display settings."})
                        continue
                    cols, rows = int(size["cols"]), int(size["rows"])
                    if not (2 <= cols <= 500 and 2 <= rows <= 250):
                        break
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                    if child is None:
                        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor",
                                   ME3_WINDOW_DIR=str(folder))
                        child = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                                                 env=env, start_new_session=True)
                    else:
                        child.send_signal(signal.SIGWINCH)
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            connected = False
            idle = loop.call_later(15, stopped.set)
        return ws

    app = web.Application()
    app.router.add_get(prefix, handle)
    app.router.add_get(prefix + "{name}", handle)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    idle = loop.call_later(90, stopped.set)
    try:
        lock.seek(0)
        lock.truncate()
        lock.write(url)
        lock.flush()
        print("Pi workspace " + url, flush=True)
        open_window(url, LOCAL / "pi-window-browser")
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopped.set)
        await stopped.wait()
    finally:
        idle.cancel()
        if child and child.poll() is None:
            child.terminate()
            try:
                await asyncio.to_thread(child.wait, 4)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait)
        os.close(master)
        os.close(slave)
        await runner.cleanup()


def main():
    LOCAL.mkdir(exist_ok=True)
    path = LOCAL / "pi-window.lock"
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Pi already has a project window open. " + lock.read().strip())
            return
        with tempfile.TemporaryDirectory(prefix="me3-window-") as folder:
            asyncio.run(serve(sys.argv[1:], Path(folder), lock))


if __name__ == "__main__":
    main()
