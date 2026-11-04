#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${ME3_PYTHON:-python3.13}"
"$python_bin" -m venv .venv313
.venv313/bin/python -m pip install -e '.[test,mcp]'
.venv313/bin/python -m pip install -r requirements-duplex.txt
if ! command -v pi >/dev/null; then
  npm install --prefix .local/pi-cli @earendil-works/pi-coding-agent@0.84.2
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
mkdir -p .local/pi
chmod 700 .local/pi
if [[ "${1:-}" == '--speech-server' ]]; then
  speech_python="${ME3_SPEECH_PYTHON:-}"
  if [[ -z "$speech_python" ]]; then
    if command -v python3.12 >/dev/null; then
      speech_python="$(command -v python3.12)"
    else
      if ! command -v uv >/dev/null; then
        printf '%s\n' 'Kokoro requires Python 3.12; set ME3_SPEECH_PYTHON or install uv.' >&2
        exit 2
      fi
      UV_CACHE_DIR="$PWD/.local/uv-cache" uv python install --install-dir "$PWD/.local/python" 3.12
      for candidate in "$PWD"/.local/python/cpython-3.12.*/bin/python3.12; do
        if [[ -x "$candidate" ]]; then speech_python="$candidate"; break; fi
      done
    fi
  fi
  "$speech_python" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Speech service requires Python 3.12 for Misaki"'
  "$speech_python" -m venv .speech-venv312
  .speech-venv312/bin/python -m pip install -e '.[speech-server]'
fi
printf '%s\n' 'Installed. Fill .env with your API settings, then run scripts/me3.sh doctor.'
