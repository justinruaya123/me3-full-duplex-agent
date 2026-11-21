"""Publish a Pi-generated single-page site in a private, request-scoped directory."""

import asyncio
import errno
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from me3.website import BUNDLE_PREFIX, prepare_website


async def build_site(root: Path, request: str, html: str) -> dict:
    if not isinstance(request, str) or not 0 < len(request) <= 1024:
        raise ValueError("A current Pi request is required")
    key = hashlib.sha256(request.encode()).hexdigest()
    dest = root / key
    index = dest / "site" / "index.html"
    receipt = dest / "verification.json"
    result = {"index": str(index.resolve()), "receipt": str(receipt.resolve())}
    if index.is_file() and receipt.is_file():
        return result
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as folder:
        stage = Path(folder) / "build"
        stage.mkdir()
        bundle = json.dumps({"files": {"index.html": html}}, ensure_ascii=False)
        await prepare_website(BUNDLE_PREFIX + bundle, stage, lambda: True)
        try:
            stage.rename(dest)
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not (index.is_file() and receipt.is_file()):
                raise
    return result


if __name__ == "__main__":
    try:
        data = sys.stdin.buffer.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("Site input exceeds 1 MiB")
        req = json.loads(data)
        result = asyncio.run(build_site(Path(".local/voicechat-sites"), req["request"], req["html"]))
        print(json.dumps(result))
    except Exception as exc:
        sys.exit(str(exc))
