#!/usr/bin/env bash
# Run the installed class benchmark with one fresh ME3 runtime per recording.
set -euo pipefail
cd "$(dirname "$0")/.."
project="$PWD"
umask 077
set -a
source "${ME3_ENV_FILE:-.env}"
set +a
bench=$(cd "${FDBENCH_DIR:-.local/fd-benchmark-20261107}" && pwd)
runtime=.venv313
if [[ "$(uname -s)" == Linux && -x .venv-pi/bin/python ]]; then runtime=.venv-pi; fi
export FDBENCH_ASSISTANT_PYTHON="${FDBENCH_ASSISTANT_PYTHON:-$project/$runtime/bin/python}"
export FDBENCH_PROJECT="$project" FDBENCH_ENTRY="$project/integrations/fdbench_entry.py"
export ME3_BENCHMARK_PROFILE=course
instance="me3-$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -p .local/qualification
control=("$FDBENCH_ASSISTANT_PYTHON" "$project/integrations/benchmark_control.py")
common=(--control-dir "/tmp/$instance" --instance "$instance")
quote_command() { "$FDBENCH_ASSISTANT_PYTHON" -c 'import shlex,sys; print(shlex.join(sys.argv[1:]))' "$@"; }
serve=$(quote_command "${control[@]}" serve "${common[@]}" --project "$project" \
    --launcher "$bench/launch_assistant.py" --python "$FDBENCH_ASSISTANT_PYTHON" \
    --log-root "$project/.local/qualification/$instance")
reset=$(quote_command "${control[@]}" reset "${common[@]}")
if [[ ! -t 0 || ! -t 1 ]]; then
  set -- --no-live "$@"
fi
cd "$bench"
exec .venv/bin/python -m fdbench run --student me3-local --rounds 1 --phrases 3 --runs 1 \
  --gap 6 --seed 231 --connect direct --where local --recordings r --yes \
  --judge-provider none --no-utmos --asr-model small --assistant-cmd "$serve" --reset-cmd "$reset" "$@"
