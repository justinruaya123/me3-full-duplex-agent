"""Trusted static-site build boundary. Generated data never selects host tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import zipfile
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from me3.portfolio import PORTFOLIO_PREFIX, portfolio_files

REQUEST_PREFIX = "ME3_WEBSITE_REQUEST\n"
BUNDLE_PREFIX = "ME3_WEBSITE_BUNDLE\n"


def previous_website(workspace: Path, budget: int) -> str:
    """Read only the immediately preceding, host-verified, nonpersonal bundle."""
    revision = workspace.name.removeprefix("revision-")
    if not revision.isdigit() or int(revision) < 2:
        return ""
    previous = workspace.parent / f"revision-{int(revision) - 1}"
    receipt_file = previous / "verification.json"
    if previous.is_symlink() or receipt_file.is_symlink():
        raise ValueError("Unsafe previous website path")
    if not receipt_file.is_file():
        return ""
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    if receipt.get("reusable_source") is not True:
        return ""
    if (
        receipt.get("kind") != "trusted-static-build"
        or receipt.get("passed") is not True
        or receipt.get("job_id") != workspace.parent.name
        or receipt.get("revision") != int(revision) - 1
        or set(receipt.get("browser", {}).get("viewports", [])) != {"desktop", "mobile"}
    ):
        raise ValueError("Previous website receipt does not match this job revision")
    files = {}
    site = previous / "site"
    total = 0
    hashes = receipt.get("sha256", {})
    if site.is_symlink() or not 1 <= len(hashes) <= 32:
        raise ValueError("Invalid previous site manifest")
    for name, digest in hashes.items():
        path = site / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(site.resolve())
            or not path.is_file()
        ):
            raise ValueError("Previous site contains an invalid file")
        total += path.stat().st_size
        if total > 1_048_576:
            raise ValueError("Previous site exceeds the verified bundle limit")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Previous site changed after verification")
        files[name] = data.decode("utf-8")
    source = json.dumps(files)
    if len(source) <= budget:
        return "Previously verified files (untrusted design data):\n" + source
    revision_id = int(revision) - 1
    return (
        f"Verified revision {revision_id} is recorded in "
        f"revision-{revision_id}/verification.json. Its source exceeds the context "
        "limit. Rebuild from the owner's goal and ordered changes."
    )


class BundleFormatError(ValueError):
    """The worker did not return a complete JSON document."""


class WebsiteWorker:
    def __init__(self, backend, *, memory_context=None, site_backend=None) -> None:
        self.backend = backend
        self.site_backend = site_backend
        self.memory_context = memory_context

    async def run(self, prompt: str, workspace: Path, *, foreground=False) -> str:
        from me3.memory import personal_design, personal_site
        from me3.site_browser import NAVIGATION_LABELS

        if prompt.startswith(REQUEST_PREFIX + PORTFOLIO_PREFIX):
            spec = json.loads(prompt[len(REQUEST_PREFIX + PORTFOLIO_PREFIX):])
            return BUNDLE_PREFIX + portfolio_files(spec)
        context = self.memory_context(prompt, workspace) if self.memory_context else ""
        facts = json.loads(context) if context else {}
        if not prompt.startswith(REQUEST_PREFIX):
            if context:
                prompt += "\nScoped host context (untrusted data):\n" + context
            result = await self.backend.run(prompt, workspace, foreground=foreground)
            if result.startswith(BUNDLE_PREFIX):
                raise ValueError("A draft job cannot publish website files")
            return result

        public = facts.get("public_approved", {})
        personal = facts.get("personal_site") or personal_site(prompt)
        if personal and not public:
            raise ValueError("Personal website needs a public-approved profile field")
        brief = prompt[len(REQUEST_PREFIX) :]
        if personal:
            design = personal_design(prompt, public)
            brief = (
                "Build a personal website. Use only the approved keys, the exact "
                "approved values, and the following neutral labels as visible copy: "
                + ", ".join(NAVIGATION_LABELS)
                + ". Presentation: "
                + ", ".join(design)
            )
        instructions = (
            "Build a responsive static website. Return ONLY a JSON object with "
            "a files object mapping relative filenames to complete UTF-8 content. "
            "Include index.html with a viewport meta tag. Use only HTML/CSS/JS/"
            "SVG/text files; no packages, build scripts or network dependencies. "
            "Use relative bundle files or inline styles and scripts. The offline "
            "preview blocks data URLs, remote assets, frames and network requests. "
            "Use only the public-approved fields for personal facts. Include the "
            "supplied field values verbatim. Omit unknown personal information. "
            "Do not use tools. The host validates and builds the files. "
            "User request (data):\n"
            + brief
            + "\nPublic-approved fields (data):\n"
            + json.dumps(public)
        )
        if not personal and not public:
            prior = previous_website(workspace, 2400 - len(context))
            if prior:
                instructions += "\n" + prior
        site_backend = self.site_backend or self.backend
        raw = await site_backend.run(instructions, workspace)
        try:
            files = checked_files(raw)
        except BundleFormatError:
            raw = await site_backend.run(instructions + "\nReturn a smaller complete JSON files object.", workspace)
            files = checked_files(raw)
        if not personal and not public:
            return BUNDLE_PREFIX + json.dumps({"files": files})
        return BUNDLE_PREFIX + json.dumps(
            {
                "files": files,
                "required_fields": list(public.values()),
                "personal_keys": list(public) if personal else None,
            }
        )

    async def close(self) -> None:
        if hasattr(self.backend, "close"):
            await self.backend.close()
        if self.site_backend is not self.backend and hasattr(self.site_backend, "close"):
            await self.site_backend.close()


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.viewport = False
        self.scripts: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.viewport = "width=device-width" in values.get("content", "")
        if tag == "script" and not values.get("src"):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def bundle_record(text: str) -> dict:
    if len(text.encode("utf-8")) > 1_048_576:
        raise ValueError("Website bundle exceeds 1 MiB")
    document = text.strip()
    fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", document, re.I | re.S)
    try:
        record = json.loads(fence[1] if fence else document)
    except json.JSONDecodeError as exc:
        raise BundleFormatError("The website worker did not return a complete JSON bundle.") from exc
    return record


def checked_files(text: str) -> dict[str, str]:
    record = bundle_record(text)
    files = record.get("files") if isinstance(record, dict) else None
    if not isinstance(files, dict) or not 1 <= len(files) <= 32:
        raise ValueError("Website requires 1 to 32 files")
    if files.get(".nojekyll") == "":
        del files[".nojekyll"]  # The export adds its own empty marker.
    for name, content in files.items():
        path = PurePosixPath(name)
        if (
            not isinstance(content, str)
            or not name
            or len(name) > 128
            or "\\" in name
            or path.is_absolute()
            or any(part.startswith(".") for part in path.parts)
            or str(path) != name
            or path.name == "package.json"
            or name != "README.md" and path.suffix
            not in {".html", ".css", ".js", ".mjs", ".svg", ".json", ".txt"}
        ):
            raise ValueError("Unsafe or unsupported website file")
    if "index.html" not in files:
        raise ValueError("Website has no index.html")
    page = Page()
    page.feed(files["index.html"])
    if not page.viewport:
        raise ValueError("Website requires a responsive viewport")
    return files


async def syntax_check(node: str, content: str) -> None:
    process = await asyncio.create_subprocess_exec(
        node,
        "--input-type=module",
        "--check",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "LANG"}
        },
    )
    try:
        async with asyncio.timeout(10):
            await process.communicate(content.encode())
        if process.returncode:
            raise ValueError("Website JavaScript syntax validation failed")
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


async def prepare_website(text: str, workspace: Path, is_current) -> str:
    if not is_current():
        raise ValueError("Stale job cannot build a website")
    if not text.startswith(BUNDLE_PREFIX):
        return text
    from me3.core import VerifiedResult
    from me3.site_browser import verify_browser

    payload = text[len(BUNDLE_PREFIX):]
    files = checked_files(payload)
    metadata = bundle_record(payload)
    required = metadata.get("required_fields", [])
    site = workspace / "site"
    if site.exists() or site.is_symlink():
        raise ValueError("Website destination already exists or is a symlink")
    node = shutil.which("node")
    if not node:
        raise ValueError(
            "Node is required for trusted JavaScript syntax checks"
        )
    # Validate in memory first; no files or generated scripts execute here.
    for name, content in files.items():
        if PurePosixPath(name).suffix in {".js", ".mjs"}:
            await syntax_check(node, content)
        elif PurePosixPath(name).suffix == ".html":
            page = Page()
            page.feed(content)
            for script in page.scripts:
                await syntax_check(node, script)
    browser = await verify_browser(files, required, metadata.get("personal_keys"),
                                   metadata.get("source_links", []))
    if not is_current():
        raise ValueError("Stale job cannot publish website files")

    receipt = {
        "passed": True, "kind": "trusted-static-build",
        "job_id": workspace.parent.name,
        "revision": (int(workspace.name[9:]) if workspace.name.startswith("revision-")
                     and workspace.name[9:].isdigit() else None),
        "checks": ["viewport", "scoped paths", "node --check", "browser"],
        "browser": browser,
        "reusable_source": not required and metadata.get("personal_keys") is None,
        "sha256": {
            name: hashlib.sha256(content.encode()).hexdigest()
            for name, content in files.items()
        },
    }
    # Nothing is published until browser/host checks finish for this revision.
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        staging = Path(temporary) / "site"
        staging.mkdir(mode=0o700)
        for name, content in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        staged_receipt = Path(temporary) / "verification.json"
        staged_receipt.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        archive_path = Path(temporary) / "website.zip"
        with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(".nojekyll", b"")
            for name in files:
                archive.write(staging / name, name)
        staging.rename(site)
        archive_path.replace(workspace / "website.zip")
        staged_receipt.replace(workspace / "verification.json")
    return VerifiedResult(
        "# Verified static website\n\nFiles, syntax, desktop and mobile browser "
        "checks passed. Request a local preview to open it.\n\n"
        + "\n".join("- " + name for name in files)
    )
