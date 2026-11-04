"""Trusted static-site build boundary. Generated data never selects host tools."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

REQUEST_PREFIX = 'ME3_WEBSITE_REQUEST\n'
BUNDLE_PREFIX = 'ME3_WEBSITE_BUNDLE\n'


class WebsiteWorker:
    def __init__(self, backend) -> None:
        self.backend = backend

    async def run(self, prompt: str, workspace: Path, *, foreground=False) -> str:
        if not prompt.startswith(REQUEST_PREFIX):
            return await self.backend.run(prompt, workspace, foreground=foreground)
        instructions = (
            'Build a responsive static website. Return ONLY a JSON object with '
            'a files object mapping relative filenames to complete UTF-8 content. '
            'Include index.html with a viewport meta tag. Use only HTML/CSS/JS/'
            'SVG/text files; no packages, build scripts or network dependencies. '
            'Do not use tools. The host validates and builds the files. '
            'User request (data):\n' + prompt[len(REQUEST_PREFIX):]
        )
        text = await self.backend.run(instructions, workspace)
        return BUNDLE_PREFIX + text

    async def close(self) -> None:
        if hasattr(self.backend, 'close'):
            await self.backend.close()


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.viewport = False
        self.scripts: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name', '').lower() == 'viewport':
            self.viewport = 'width=device-width' in values.get('content', '')
        if tag == 'script' and not values.get('src'):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(''.join(self.current))
            self.current = None


def checked_files(text: str) -> dict[str, str]:
    if len(text.encode('utf-8')) > 1_048_576:
        raise ValueError('Website bundle exceeds 1 MiB')
    record = json.loads(text)
    files = record.get('files') if isinstance(record, dict) else None
    if not isinstance(files, dict) or not 1 <= len(files) <= 32:
        raise ValueError('Website requires 1 to 32 files')
    for name, content in files.items():
        path = PurePosixPath(name)
        if (not isinstance(content, str) or not name or len(name) > 128
                or '\\' in name or path.is_absolute()
                or any(part.startswith('.') for part in path.parts)
                or str(path) != name or path.name == 'package.json'
                or path.suffix not in {'.html', '.css', '.js', '.mjs',
                                       '.svg', '.json', '.txt'}):
            raise ValueError('Unsafe or unsupported website file')
    if 'index.html' not in files:
        raise ValueError('Website has no index.html')
    page = Page()
    page.feed(files['index.html'])
    if not page.viewport:
        raise ValueError('Website requires a responsive viewport')
    return files


async def syntax_check(node: str, content: str) -> None:
    process = await asyncio.create_subprocess_exec(
        node, '--input-type=module', '--check',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={key: value for key, value in os.environ.items()
             if key in {'PATH', 'HOME', 'TMPDIR', 'LANG'}},
    )
    try:
        async with asyncio.timeout(10):
            await process.communicate(content.encode())
        if process.returncode:
            raise ValueError('Website JavaScript syntax validation failed')
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


async def prepare_website(text: str, workspace: Path, is_current) -> str:
    if not is_current():
        raise ValueError('Stale job cannot build a website')
    if not text.startswith(BUNDLE_PREFIX):
        return text
    files = checked_files(text[len(BUNDLE_PREFIX):])
    site = workspace / 'site'
    if site.exists() or site.is_symlink():
        raise ValueError('Website destination already exists or is a symlink')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node is required for trusted JavaScript syntax checks')
    # Validate in memory first; no files or generated scripts execute here.
    for name, content in files.items():
        if PurePosixPath(name).suffix in {'.js', '.mjs'}:
            await syntax_check(node, content)
        elif PurePosixPath(name).suffix == '.html':
            page = Page()
            page.feed(content)
            for script in page.scripts:
                await syntax_check(node, script)
    if not is_current():
        raise ValueError('Stale job cannot publish website files')
    # No await between the final revision check and the scoped writes.
    site.mkdir(mode=0o700)
    for name, content in files.items():
        target = site / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    receipt = {
        'passed': True, 'kind': 'trusted-static-build',
        'checks': ['viewport', 'scoped paths', 'node --check'],
        'responsive_browser_test': 'not run',
        'sha256': {name: hashlib.sha256(content.encode()).hexdigest()
                   for name, content in files.items()},
    }
    (workspace / 'verification.json').write_text(json.dumps(receipt, indent=2))
    return ('# Verified static website\n\nFiles and JavaScript syntax checks passed. '
            'A responsive viewport is present; browser/acoustic tests are separate. '
            'Local preview requires an explicit launch request.\n\n'
            + '\n'.join('- ' + name for name in files))
