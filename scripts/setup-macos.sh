#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
client_env="${ME3_ENV_FILE:-.env}"
if [[ "${1:-}" != '--speech-server-only' ]]; then
  python_bin="${ME3_PYTHON:-python3.13}"
  if [[ ! -x .venv313/bin/python ]]; then "$python_bin" -m venv .venv313; fi
  signature="$(shasum -a 256 pyproject.toml requirements-duplex.txt scripts/setup-macos.sh)"
  receipt=.venv313/.me3-client-install
  if [[ ! -f "$receipt" || "$(<"$receipt")" != "$signature" ]]; then
    .venv313/bin/python -m pip install -e '.[test,mcp,local-tts,website]'
    .venv313/bin/python -m pip install -r requirements-duplex.txt
    printf '%s\n' "$signature" > "$receipt"
  fi
  .venv313/bin/python -m playwright install chromium
  pi_bin=".local/pi-cli/node_modules/.bin/pi"
  if [[ ! -x "$pi_bin" ]]; then pi_bin="$(command -v pi || true)"; fi
  if [[ -z "$pi_bin" || "$("$pi_bin" --version 2>/dev/null)" != "0.84.2" ]]; then
    npm install --prefix .local/pi-cli @earendil-works/pi-coding-agent@0.84.2
  fi
  ./scripts/setup-openintelligentui.sh
  mkdir -p .local/pi
  chmod 700 .local/pi
fi
if [[ "${1:-}" != --speech-server-only && ! -f "$client_env" ]]; then
  (umask 077; cp .env.example "$client_env")
fi
if [[ "${1:-}" == '--speech-server' || "${1:-}" == '--speech-server-only' ]]; then
  if [[ ! -f .env.speech-server ]]; then
    (
      umask 077
      set -C
      source .env.speech.example
      if [[ -f "$client_env" ]]; then source "$client_env"; fi
      ME3_SPEECH_SERVER_TOKEN="${ME3_SPEECH_SERVER_TOKEN:-${ME3_ASR_API_KEY:-}}"
      for key in ME3_ASR_MODEL ME3_TTS_MODEL ME3_TTS_VOICE ME3_SPEECH_SERVER_TOKEN; do
        printf '%s=%q\n' "$key" "${!key}"
      done > .env.speech-server
    )
  fi
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
if [[ "${1:-}" == '--speech-server-only' ]]; then
  printf '%s\n' 'Speech service installed. Configure .env.speech-server, then run scripts/me3.sh speech --check.'
else
  (
    source "$client_env"
    if [[ "${ME3_TTS_BACKEND:-local}" == local ]]; then
      .venv313/bin/python scripts/install-kokoro.py "${ME3_KOKORO_DIR:-.local/models/kokoro-int8-multi-lang-v1_0}"
    fi
  )
  printf '%s\n' 'Client installed. Run scripts/me3.sh doctor for configuration status.'
fi
