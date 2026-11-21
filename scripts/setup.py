#!/usr/bin/env python3
"""Save ME3 credentials in the private client environment file."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import warnings

ROOT = Path(__file__).resolve().parents[1]
CLIENT_KEYS = {
    "OPENROUTER_API_KEY": "OpenRouter",
    "BRAVE_SEARCH_API_KEY": "Brave Web Search",
    "BRAVE_ANSWERS_API_KEY": "Brave Answers (if separate)",
    "ME3_FOREGROUND_API_KEY": "Direct conversation endpoint",
    "ME3_WORKER_API_KEY": "Direct worker endpoint",
    "ME3_SPEAKER_API_KEY": "Local speaker verifier",
}


def save_keys(path: Path, template: Path, answers: dict[str, str]) -> None:
    updates = {key: value for key, value in answers.items() if value.strip()}
    path = path.resolve()
    if path.exists() and not updates:
        return
    if path == template.resolve():
        raise ValueError("Choose a private environment file for credentials, not the example template")
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        _write_keys(path, template, updates)
    finally:
        os.close(directory)


def _write_keys(path: Path, template: Path, updates: dict[str, str]) -> None:
    if path.exists() and not updates:
        return
    original = (path if path.exists() else template).read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    for key, value in updates.items():
        if any(char in value for char in "\0\r\n"):
            raise ValueError(f"{key} must be on one line")
        pattern = re.compile(rf"^([ \t]*(?:export[ \t]+)?){re.escape(key)}=")
        assignment = f"{key}={shlex.quote(value)}"
        found = False
        for i, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                # Refuse to cut an operator's multiline assignment in half.
                try:
                    tokens = shlex.shlex(line.rstrip("\r\n"), posix=True,
                                         punctuation_chars=True)
                    tokens.whitespace_split = True
                    words = list(tokens)
                    if words[:1] == ["export"]:
                        words = words[1:]
                    if len(words) != 1:
                        raise ValueError
                except ValueError:
                    raise ValueError(f"Edit the compound or multiline {key} assignment manually") from None
                ending = line[len(line.rstrip("\r\n")):]
                lines[i] = match[1] + assignment + ending
                found = True
        if not found:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(assignment + "\n")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        try:
            temp.write("".join(lines).encode("utf-8"))
            temp.flush()
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def configure(client: Path, with_server: bool, prompt) -> None:
    answers = {}
    if with_server:
        shared = prompt("Shared Whisper / server Kokoro token")
        answers.update(ME3_ASR_API_KEY=shared, ME3_TTS_API_KEY=shared)
    else:
        answers["ME3_ASR_API_KEY"] = prompt("Whisper server token")
        answers["ME3_TTS_API_KEY"] = prompt("Server Kokoro token (optional for local speech)")
    for key, label in CLIENT_KEYS.items():
        answers[key] = prompt(f"{label} ({key})")
    save_keys(client, ROOT / ".env.example", answers)
    if with_server and shared.strip():
        save_keys(ROOT / ".env.speech-server", ROOT / ".env.speech.example",
                  {"ME3_SPEECH_SERVER_TOKEN": shared})


def run_wizard(*, no_prompt=False, with_server=False, brave_only=False) -> None:
    client = ROOT / (os.environ.get("ME3_ENV_FILE") or ".env")
    if no_prompt or not sys.stdin.isatty():
        def prompt(_label):
            return ""
    else:
        print("Optional credentials are hidden. Press Enter to keep a saved value or skip a missing key.")
        def prompt(label):
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    return getpass.getpass(label + ": ")
                except getpass.GetPassWarning:
                    raise ValueError("Use an interactive terminal for hidden input or --no-prompt") from None
    if brave_only:
        keys = {key: prompt(CLIENT_KEYS[key])
                for key in ("BRAVE_SEARCH_API_KEY", "BRAVE_ANSWERS_API_KEY")}
        save_keys(client, ROOT / ".env.example", keys)
    else:
        configure(client, with_server, prompt)
    print(f"Client configuration ready at {client.resolve()}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-prompt", action="store_true", help="skip all key prompts")
    parser.add_argument("--brave-key", action="store_true", help="prompt only for Brave keys")
    parser.add_argument("--speech-server", action="store_true", help="also configure the local speech server")
    args = parser.parse_args()
    try:
        run_wizard(no_prompt=args.no_prompt, with_server=args.speech_server, brave_only=args.brave_key)
    except KeyboardInterrupt:
        sys.exit(130)
    except (ValueError, OSError, EOFError) as exc:
        sys.exit(str(exc))
