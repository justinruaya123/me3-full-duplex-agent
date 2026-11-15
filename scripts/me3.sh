#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
# Keep orchestration/audio local; MLX uses its separate Mac environment.
runtime_python=.venv313/bin/python
if [[ "$(uname -s)" == Linux && -x .venv-pi/bin/python ]]; then
  runtime_python=.venv-pi/bin/python
fi
if [[ -z "${ME3_PI_BIN:-}" && -x .local/pi-cli/node_modules/.bin/pi ]]; then
  export ME3_PI_BIN="$PWD/.local/pi-cli/node_modules/.bin/pi"
fi
mode="${1:-console}"
if [[ $# -gt 0 ]]; then shift; fi
case "$mode" in
  doctor) exec "$runtime_python" -m me3.doctor "$@" ;;
  console) exec "$runtime_python" -m me3.runtime "$@" ;;
  voice) exec "$runtime_python" -m me3.runtime --voice "$@" ;;
  speech) exec .speech-venv312/bin/python -m me3.speech_server "$@" ;;
  pi) exec "${ME3_PI_BIN:-pi}" "$@" ;;
  *) printf '%s\n' 'Usage: scripts/me3.sh {doctor|console|voice|speech|pi} [args]' >&2; exit 2 ;;
esac
