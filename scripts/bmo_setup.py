"""Bootstrap the project-local BMO voice agent and move its editable settings."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import warnings

from scripts.setup import save_keys

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("OPENROUTER_API_KEY", "DEEPGRAM_API_KEY", "BRAVE_SEARCH_API_KEY", "BRAVE_ANSWERS_API_KEY")
PORTABLE = {
    "ME3_FOREGROUND_PROVIDER", "ME3_FOREGROUND_MODEL", "ME3_FOREGROUND_THINKING",
    "ME3_WORKER_PROVIDER", "ME3_WORKER_MODEL", "ME3_WORKER_THINKING",
    "ME3_WEBSITE_THINKING", "ME3_VOICE_TTS", "ME3_MEMORY_ENABLED", "ME3_ASR_BACKEND",
}
PROMPTS = {"SYSTEM.md", "SOUL.md", "TOOLS.md", "USER.md", "USERS.md", "WORKER.md"}


def settings(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r"^\s*(?:export\s+)?(\w+)=(.*)$", line)
            if match and match[1] in PORTABLE:
                words = shlex.split(match[2], comments=True)
                if words:
                    values[match[1]] = " ".join(words)
    return values


def validate(values, prompts):
    if not isinstance(values, dict) or not isinstance(prompts, dict):
        raise ValueError("Invalid settings or prompts in config")
    for key, value in values.items():
        if key not in PORTABLE or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:+-]{0,199}", value):
            raise ValueError(f"Nonportable setting {key!r}")
    for name, value in prompts.items():
        if name not in PROMPTS or not isinstance(value, str) or len(value.encode()) > 8192:
            raise ValueError(f"Invalid prompt {name!r} (limit 8192 bytes)")


def private_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(data.encode())
            tmp.flush()
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


def export_config(root, path, env_file=None, prompts_dir=None):
    if path.exists() or path.is_symlink():
        raise ValueError("Choose a new filename for the export")
    prompts_dir = prompts_dir or root / ".local/voice-prompts"
    prompts = {n: (prompts_dir / n).read_text() for n in PROMPTS
               if (prompts_dir / n).is_file() and not (prompts_dir / n).is_symlink()}
    values = settings(env_file or root / ".env")
    validate(values, prompts)
    private_write(path, json.dumps(dict(version=1, settings=values, prompts=prompts),
                                   indent=2, ensure_ascii=False) + "\n")


def import_config(root, path, replace=False):
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Config exceeds 128 KiB")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("version") != 1 or set(data) != {"version", "settings", "prompts"}:
        raise ValueError("Unsupported config bundle")
    values, prompts = data["settings"], data["prompts"]
    validate(values, prompts)
    folder = root / ".local/voice-prompts"
    if folder.resolve() != root.resolve() / ".local/voice-prompts":
        raise ValueError("Unexpected prompt directory symlink")
    for name, content in prompts.items():
        target = folder / name
        if target.is_symlink() or (target.exists() and not replace and target.read_text() != content):
            raise ValueError(f"Existing prompt {name} differs. Review it or use --replace-prompts.")
    save_keys(root / ".env", root / ".env.bmo.example", values)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, content in prompts.items():
        private_write(folder / name, content)


def configure(root, no_prompt):
    if not no_prompt and sys.stdin.isatty():
        print("Enter to keep an existing key or skip. Brave Answers can share the Brave Search key.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                answers = {key: getpass.getpass(key + ": ") for key in KEYS}
            except getpass.GetPassWarning:
                raise ValueError("Use a terminal for hidden key entry or pass --no-prompt") from None
    else:
        answers = {}
    save_keys(root / ".env", root / ".env.bmo.example", answers)
    folder = root / ".local/voice-prompts"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for template in (root / "integrations/voicechat/templates").glob("*.md"):
        if not (folder / template.name).exists():
            private_write(folder / template.name, template.read_text())
    print("Private settings:", root / ".env", flush=True)


NODE_RELEASE = "v24.13.0"
NODE_HASHES = {
    "linux-arm64": "0f6d40b94c6a2eb6b4c240ffc8b9fd3ada7ab044c177dd413c06e1ef9a63f081",
    "linux-x64": "6223aad1a81f9d1e7b682c59d12e2de233f7b4c37475cd40d1c89c42b737ffa8",
    "darwin-arm64": "d595961e563fcae057d4a0fb992f175a54d97fcc4a14dc2d474d92ddeea3b9f8",
    "darwin-x64": "6f03c1b48ddbe1b129a6f8038be08e0899f05f17185b4d3e4350180ab669a7f3",
}


def prepare_node(root):
    local = root / ".local/node"
    if (local / "bin/node").is_file():
        os.environ["PATH"] = str(local / "bin") + os.pathsep + os.environ["PATH"]
    if shutil.which("npm") and shutil.which("node"):
        version = subprocess.check_output(["node", "-p", "process.versions.node"], text=True)
        if tuple(map(int, version.strip().split(".")[:2])) >= (22, 19):
            return
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64"}.get(platform.machine())
    target = platform.system().lower() + "-" + str(arch)
    if target not in NODE_HASHES or local.exists():
        raise ValueError("Install Node 22.19+ and npm or repair the project .local/node runtime")
    local.parent.mkdir(mode=0o700, exist_ok=True)
    name = "node-" + NODE_RELEASE + "-" + target
    with tempfile.TemporaryDirectory(dir=local.parent) as tmp:
        archive = Path(tmp) / "node.tgz"
        subprocess.run(["curl", "--proto", "=https", "-fsSL", "--max-time", "180", "-o", archive,
                        f"https://nodejs.org/dist/{NODE_RELEASE}/{name}.tar.gz"], check=True)
        with archive.open("rb") as stream:
            if hashlib.sha256(stream.read()).hexdigest() != NODE_HASHES[target]:
                raise ValueError("Node release checksum mismatch for " + target)
        subprocess.run(["tar", "-xzf", archive, "-C", tmp], check=True)
        (Path(tmp) / name).rename(local)
    os.environ["PATH"] = str(local / "bin") + os.pathsep + os.environ["PATH"]


def install(root, system_deps=False):
    if system_deps:
        if platform.system() == "Linux":
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(["sudo", "apt-get", "install", "-y", "git", "curl", "python3-venv",
                            "python3-dev", "build-essential", "pkg-config", "libportaudio2",
                            "portaudio19-dev", "libasound2-dev", "libsndfile1"], check=True)
        elif platform.system() == "Darwin":
            subprocess.run(["brew", "install", "python@3.13", "portaudio"], check=True)
    prepare_node(root)
    python = root / (".venv313" if platform.system() == "Darwin" else ".venv-pi") / "bin/python"
    if not python.exists():
        exe = os.getenv("ME3_PYTHON") or shutil.which("python3.13") or sys.executable
        subprocess.run([exe, "-c", "import sys; assert (3,11)<=sys.version_info[:2]<=(3,13), 'Use Python 3.11–3.13'"], check=True)
        subprocess.run([exe, "-m", "venv", python.parent.parent], check=True)
    def run(*args):
        subprocess.run(args, cwd=root, check=True)
    run(python, "-m", "pip", "install", "-e", ".[mcp,web,website]", "piper-tts==1.4.2",
        "soxr", "pyaudio", "-r", "requirements-duplex.txt")
    if system_deps and platform.system() == "Linux":
        run(python, "-m", "playwright", "install-deps", "chromium")
    run(python, "-m", "playwright", "install", "chromium")
    helpers = root / ".local/pi/helpers"
    subprocess.run(["npm", "ci", "--prefix", "integrations/voicechat", "--no-audit", "--no-fund"],
                   cwd=root, check=True, env=dict(os.environ,
                   PI_COMPUTER_USE_HELPER_APP_PATH=str(helpers / "pi-computer-use.app"),
                   PI_COMPUTER_USE_LINUX_HELPER_PATH=str(helpers / "linux-bridge")))
    run("bash", "scripts/setup-openintelligentui.sh")
    run(python, "-m", "integrations.voicechat.face_assets")
    run(python, "-m", "me3.bmo", "--root", str(root / ".local/models/bmo-v1.0-voice"))
    subprocess.run(["node", "integrations/voicechat/project.mjs"], cwd=root, check=True,
                   env=dict(os.environ, ME3_CLIENT_HOME=str(root), PI_CODING_AGENT_DIR=str(root / ".local/pi")))
    print("Ready. Run python3 setup.py run, then /me3 duplex.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-prompt", action="store_true", help="keep saved keys and skip missing ones")
    commands = parser.add_subparsers(dest="command")
    for name in ("install-bmo", "configure"):
        command = commands.add_parser(name)
        if name == "install-bmo":
            command.add_argument("--system-deps", action="store_true", help="install OS audio and browser prerequisites")
        command.add_argument("--no-prompt", action="store_true", default=argparse.SUPPRESS)
    launch = commands.add_parser("run")
    launch.add_argument("--window", action="store_true")
    launch.add_argument("--computer-use", action="store_true", help="enable local desktop tools for this Pi session")
    commands.add_parser("check")
    exporter = commands.add_parser("export-config")
    exporter.add_argument("file", type=Path)
    exporter.add_argument("--env-file", type=Path, help="read settings from an existing installation")
    exporter.add_argument("--prompt-dir", type=Path, help="read prompts from an existing installation")
    importer = commands.add_parser("import-config")
    importer.add_argument("file", type=Path)
    importer.add_argument("--replace-prompts", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "export-config":
            export_config(ROOT, args.file, args.env_file, args.prompt_dir)
        elif args.command == "import-config":
            import_config(ROOT, args.file, args.replace_prompts)
        elif args.command in {"run", "check"}:
            flag = "--sanity" if args.command == "check" else "--window" if args.window else "--terminal"
            os.chdir(ROOT)
            flags = ["--computer-use", flag] if getattr(args, "computer_use", False) else [flag]
            os.execvpe("bash", ["bash", "integrations/voicechat/start.sh", *flags], {"ME3_ASR_BACKEND": "deepgram", **os.environ, "ME3_CLIENT_HOME": str(ROOT)})
        else:
            configure(ROOT, args.no_prompt)
            if args.command != "configure":
                install(ROOT, getattr(args, "system_deps", False))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"BMO setup: {exc}\n")
