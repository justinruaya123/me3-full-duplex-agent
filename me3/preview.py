"""Read-only loopback previews of revision-verified static artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PreviewManager:
    def __init__(self) -> None:
        self.servers: dict[str, tuple[int, asyncio.Server, str, str]] = {}

    def stop(self, job_id: str) -> None:
        entry = self.servers.pop(job_id, None)
        if entry:
            entry[1].close()

    def stop_session(self, session_id: str) -> None:
        for job_id, entry in list(self.servers.items()):
            if entry[3] == session_id:
                self.stop(job_id)

    async def start(
        self, job: dict, root: Path, is_current, *, session_id: str
    ) -> str:
        if (
            job["status"] != "completed"
            or not job["artifact"]
            or not is_current()
        ):
            raise ValueError("Preview requires a current completed job")
        workspace = (root / job["artifact"]).parent.resolve()
        if not workspace.is_relative_to(root.resolve()):
            raise ValueError("Preview artifact escapes runtime")
        receipt = json.loads((workspace / "verification.json").read_text())
        site = workspace / "site"
        hashes = receipt.get("sha256", {})
        if (
            receipt.get("passed") is not True
            or not hashes
            or site.is_symlink()
        ):
            raise ValueError(
                "Preview requires a successful verification receipt"
            )

        def read(name):
            path = (site / name).resolve()
            if (
                name not in hashes
                or not path.is_relative_to(site.resolve())
                or not path.is_file()
            ):
                raise ValueError("Preview path is not a verified file")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != hashes[name]:
                raise ValueError("Website files changed after verification")
            return content

        for name in hashes:
            read(name)
        existing = self.servers.get(job["id"])
        if (
            existing
            and existing[0] == job["revision"]
            and existing[3] == session_id
        ):
            return existing[2]
        self.stop(job["id"])
        if len(self.servers) >= 4:
            raise ValueError(
                "Close an existing preview before opening another"
            )

        async def handle(reader, writer):
            try:
                async with asyncio.timeout(3):
                    line = await reader.readline()
                    method, target, _ = line.decode("ascii").strip().split(" ")
                    if method != "GET" or len(line) > 2048 or not is_current():
                        raise ValueError("Invalid preview request")
                    name = (
                        unquote(urlsplit(target).path).lstrip("/")
                        or "index.html"
                    )
                    content = read(name)
                    mime = mimetypes.guess_type(name)[0] or "text/plain"
                    headers = (
                        "HTTP/1.1 200 OK\r\n"
                        f"Content-Type: {mime}; charset=utf-8\r\n"
                        f"Content-Length: {len(content)}\r\n"
                        "Content-Security-Policy: default-src 'self'; "
                        "script-src 'self' 'unsafe-inline'; "
                        "style-src 'self' 'unsafe-inline'; "
                        "connect-src 'none'; form-action 'none'; "
                        "object-src 'none'; sandbox allow-scripts\r\n"
                        "X-Content-Type-Options: nosniff\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                    writer.write(headers + content)
                    await writer.drain()
            except (ValueError, OSError, TimeoutError, UnicodeError):
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        if not is_current():
            server.close()
            await server.wait_closed()
            raise ValueError("Job revised while preview was starting")
        port = server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/"
        self.servers[job["id"]] = (job["revision"], server, url, session_id)
        # Verify the running listener before reporting a usable URL.
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 3)
            if not response.startswith(b"HTTP/1.1 200 OK"):
                self.stop(job["id"])
                raise ValueError("Preview did not respond successfully")
        finally:
            writer.close()
            await writer.wait_closed()
        if not is_current():
            self.stop(job["id"])
            raise ValueError("Preview authorization expired")
        return url

    async def close(self) -> None:
        servers = [entry[1] for entry in self.servers.values()]
        self.servers.clear()
        for server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
