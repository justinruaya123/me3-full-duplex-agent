#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tts_override="${ME3_TTS_BACKEND-}"
mode="${1:-console}"
env_file=.env
if [[ -n "${ME3_ENV_FILE:-}" ]]; then
  env_file="$ME3_ENV_FILE"
  if [[ ! -f "$env_file" ]]; then
    printf 'Configuration file missing: %s\n' "$env_file" >&2
    exit 2
  fi
elif [[ "$mode" == speech && -f .env.speech-server ]]; then
  env_file=.env.speech-server
fi
if [[ -f "$env_file" ]]; then
  set -a
  source "$env_file"
  set +a
fi
if [[ -n "$tts_override" ]]; then export ME3_TTS_BACKEND="$tts_override"; fi
# Keep orchestration/audio local; MLX uses its separate Mac environment.
runtime_python=.venv313/bin/python
if [[ "$(uname -s)" == Linux && -x .venv-pi/bin/python ]]; then
  runtime_python=.venv-pi/bin/python
fi
if [[ -z "${ME3_PI_BIN:-}" && -x .local/pi-cli/node_modules/.bin/pi ]]; then
  export ME3_PI_BIN="$PWD/.local/pi-cli/node_modules/.bin/pi"
fi
if [[ $# -gt 0 ]]; then shift; fi
case "$mode" in
  tts-probe) exec "$runtime_python" -m me3.tts_probe "$@" ;;
  doctor) exec "$runtime_python" -m me3.doctor "$@" ;;
  web) exec "$runtime_python" -m me3.web_client.server "$@" ;;
  console) exec "$runtime_python" -m me3.runtime "$@" ;;
  voice) exec "$runtime_python" -m me3.runtime --voice "$@" ;;
  speech) exec .speech-venv312/bin/python -m me3.speech_server "$@" ;;
  pi) exec "${ME3_PI_BIN:-pi}" "$@" ;;
  *) printf '%s\n' 'Usage: scripts/me3.sh {doctor|console|web|voice|speech|tts-probe|pi} [args]' >&2; exit 2 ;;
esac
