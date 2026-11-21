"""Install the release archive into the configured client voice directory."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from me3.local_tts import BUNDLE, verify_assets

ARCHIVE_SHA256 = "72c347230107ef8a31098ec4d468a605244beef5f1ed00db97efa13518800653"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{BUNDLE}.tar.bz2"


def install(target: Path) -> None:
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        verify_assets(target)
        print(f"Verified local Kokoro in {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as staging:
        archive = Path(staging, "kokoro.tar.bz2")
        subprocess.run(["curl", "--fail", "--location", "--retry", "2",
                        "--output", str(archive), URL], check=True)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Kokoro archive checksum mismatch")
        with tarfile.open(archive, "r:bz2") as package:
            package.extractall(staging, filter="data")
        bundle = Path(staging, BUNDLE)
        verify_assets(bundle)
        bundle.rename(target)
    print(f"Installed local Kokoro in {target}")


if __name__ == "__main__":
    install(Path(sys.argv[1]).expanduser())
