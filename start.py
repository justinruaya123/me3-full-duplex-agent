#!/usr/bin/env python3
"""Set up the ME3 Mac client and open the Pi terminal."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.setup import run_wizard

ROOT = Path(__file__).resolve().parent


def prerequisites(with_server: bool) -> None:
    brew = shutil.which("brew")
    packages = []
    for command in ("git", "gh"):
        if not shutil.which(command):
            packages.append(command)
    if not shutil.which(os.environ.get("ME3_PYTHON", "python3.13")):
        if os.environ.get("ME3_PYTHON"):
            raise ValueError("ME3_PYTHON must point to an installed Python 3.13")
        packages.append("python@3.13")
    node = shutil.which("node")
    if node:
        version = subprocess.check_output([node, "-p", "process.versions.node"], text=True)
    if not node or tuple(map(int, version.strip().split(".")[:2])) < (22, 19) or not shutil.which("npm"):
        packages.append("node")
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        packages.append("pkgconf")
    if not pkg_config or subprocess.call([pkg_config, "--exists", "portaudio-2.0"]):
        packages.append("portaudio")
    if with_server and not any(shutil.which(cmd) for cmd in (
        os.environ.get("ME3_SPEECH_PYTHON", "python3.12"), "uv"
    )):
        packages.append("python@3.12")
    if packages:
        if not brew:
            raise ValueError("Install Homebrew or supply these prerequisites: " + ", ".join(packages))
        subprocess.run([brew, "install", *packages], check=True)
        prefix = subprocess.check_output([brew, "--prefix"], text=True).strip()
        os.environ["PATH"] = os.pathsep.join(
            [str(Path(prefix, "opt", package, "bin")) for package in packages]
            + [os.environ["PATH"]]
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brave-key", action="store_true", help="save only the Brave API key and exit")
    parser.add_argument("--setup-only", action="store_true", help="finish after setup")
    parser.add_argument("--no-prompt", action="store_true", help="skip all key prompts")
    parser.add_argument("--speech-server", action="store_true",
                        help="also install and configure the MLX speech service on this Mac")
    parser.add_argument("--demo", action="store_true", help="launch trusted-room voice")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.exit(2, "This bootstrap is for the Mac. Linux setup is in docs/RASPBERRY_PI_TESTING.md.\n")
    os.chdir(ROOT)
    run_wizard(no_prompt=args.no_prompt, with_server=args.speech_server, brave_only=args.brave_key)
    if args.brave_key:
        return
    prerequisites(args.speech_server)
    setup = [str(ROOT / "scripts/setup-macos.sh")]
    if args.speech_server:
        setup.append("--speech-server")
    subprocess.run(setup, check=True)
    print("For a Pi account that needs sign-in, use /login in the Pi terminal.", flush=True)
    if args.speech_server:
        print("Start the speech service in its own terminal with ME3_ENV_FILE=.env.speech-server ./scripts/me3.sh speech", flush=True)
    if not args.setup_only:
        launcher = str(ROOT / "scripts/me3.sh")
        options = ["--me3-voice-mode", "demo"] if args.demo else []
        os.execv(launcher, [launcher, "agent", *options])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (ValueError, OSError, EOFError) as exc:
        sys.exit(str(exc))
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
