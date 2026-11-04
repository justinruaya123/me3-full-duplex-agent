#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  source .env
fi
if [[ -z "${ME3_PI_BIN:-}" && -x .local/pi-cli/node_modules/.bin/pi ]]; then
  export ME3_PI_BIN="$PWD/.local/pi-cli/node_modules/.bin/pi"
fi
mode="${1:-console}"
if [[ $# -gt 0 ]]; then shift; fi
case "$mode" in
  doctor) exec .venv313/bin/python -m me3.doctor "$@" ;;
  console) exec .venv313/bin/python -m me3.runtime "$@" ;;
  voice) exec .venv313/bin/python -m me3.runtime --voice "$@" ;;
  speech) exec .speech-venv312/bin/python -m me3.speech_server "$@" ;;
  pi) exec "${ME3_PI_BIN:-pi}" "$@" ;;
  *) printf '%s\n' 'Usage: scripts/me3.sh {doctor|console|voice|speech|pi} [args]' >&2; exit 2 ;;
esac
