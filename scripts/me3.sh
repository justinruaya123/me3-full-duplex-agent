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
export ME3_PI_BIN="${ME3_PI_BIN:-$PWD/integrations/voicechat/node_modules/.bin/pi}"
export PI_CODING_AGENT_DIR="$PWD/.local/pi"
mode="${1:-console}"
if [[ $# -gt 0 ]]; then shift; fi
case "$mode" in
  doctor) exec "$runtime_python" -m me3.doctor "$@" ;;
  console) exec "$runtime_python" -m me3.runtime "$@" ;;
  voice) exec "$runtime_python" -m me3.runtime --voice "$@" ;;
  speech) exec .speech-venv312/bin/python -m me3.speech_server "$@" ;;
  pi) exec bash integrations/voicechat/start.sh "$@" ;;
  *) printf '%s\n' 'Usage: scripts/me3.sh {doctor|console|voice|speech|pi} [args]' >&2; exit 2 ;;
esac
