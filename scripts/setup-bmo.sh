#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
python="${VOICECHAT_PYTHON:-$PWD/.venv313/bin/python}"
if ! "$python" -c 'from importlib.metadata import version; assert version("piper-tts") == "1.4.2"' 2>/dev/null; then
    "$python" -m pip install --only-binary=:all: piper-tts==1.4.2
fi
"$python" -m me3.bmo --root "${ME3_BMO_DIR:-$PWD/.local/models/bmo-v1.0-voice}"
