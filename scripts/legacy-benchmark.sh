#!/usr/bin/env bash
# Full class dataset protocol, followed by the project's spoken behavior checks.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

usage='Usage: ./benchmark.sh --legacy [--smoke | --resume CLASS_RUN_DIRECTORY]'
resume=
case "${1-}" in
  "") rounds=3; phrases=10; runs=3 ;;
  --smoke) shift; rounds=1; phrases=3; runs=1 ;;
  --resume)
    [[ $# == 2 && -f "$2/queue.json" && -f "$2/session.json" ]] || { echo "$usage" >&2; exit 2; }
    resume=$(cd "$2" && pwd)
    shift 2 ;;
  -h|--help)
    echo "$usage"
    echo 'Uses ME3_ENV_FILE (default .env) and FDBENCH_DIR (the installed class checkout).'
    echo 'Install expect for unattended runs. Reports are saved under .local/benchmarks/.'
    exit 0 ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
[[ $# == 0 ]] || { echo "$usage" >&2; exit 2; }
set -a
source "${ME3_ENV_FILE:-.env}"
set +a
runtime=.venv313
if [[ $(uname -s) == Linux && -x .venv-pi/bin/python ]]; then runtime=.venv-pi; fi
python=${FDBENCH_ASSISTANT_PYTHON:-"$PWD/$runtime/bin/python"}
bench=${FDBENCH_DIR:-"$PWD/.local/fd-benchmark-20261107"}
mkdir -p .local/benchmarks
out=$(mktemp -d "$PWD/.local/benchmarks/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
student="me3-${out##*/}"
echo "Reports: $out"
printf 'stage\texit_code\n' > "$out/status.tsv"
failed=0
run_stage() {
    local name=$1 status=0
    shift
    echo "Running $name"
    "$@" > "$out/$name.log" 2>&1 || status=$?
    printf '%s\t%s\n' "$name" "$status" | tee -a "$out/status.tsv"
    if [[ $status != 0 ]]; then failed=1; fi
}

course() {
    local args=(--student "$student")
    if [[ -n "$resume" ]]; then
        args+=(--resume "$resume")
    else
        args+=(--rounds "$rounds" --phrases "$phrases" --runs "$runs")
    fi
    # The pinned scorer pauses after five missing replies, even with --yes.
    # Acknowledge that prompt once and keep every miss in the official report.
    if command -v expect >/dev/null; then
        TERM=xterm expect -f - "${args[@]}" <<'TCL' || return $?
set timeout -1
spawn -noecho ./scripts/course-benchmark.sh {*}$argv
set continued 0
expect {
    -exact "She has not said anything in the last 5 trials" {
        if {!$continued} {set continued 1; send -- " "}
        exp_continue
    }
    eof {}
}
set result [wait]
if {[llength $result] != 4 || [lindex $result 2] != 0} {exit 1}
exit [lindex $result 3]
TCL
    elif [[ -t 0 ]]; then
        ./scripts/course-benchmark.sh "${args[@]}" > /dev/tty 2>&1 || return $?
    else
        echo 'Install expect to run the pinned class scorer unattended.' >&2
        return 2
    fi
    local reports
    if [[ -n "$resume" ]]; then
        reports=("$resume/results.json")
    else
        reports=("$bench/runs/$student"/*/results.json)
    fi
    [[ -f ${reports[0]} ]] || { echo 'Class scorer produced no report.' >&2; return 1; }
    ln -s "$(cd "$(dirname "${reports[0]}")" && pwd)" "$out/course" || return 1
    "$python" - "$out/course/results.json" <<'PY'
import json
import sys
from pathlib import Path

report = Path(sys.argv[1])
queue = json.loads(report.read_text())["queue_summary"]
print(queue)
if not queue["total"] or queue["done"] != queue["total"]:
    sys.exit("Class recording queue incomplete")
for path in sorted(report.parent.glob("trials/*/timing.json")):
    trial = json.loads(path.read_text())
    if trial.get("score_error"):
        sys.exit(f"Class scoring failed for {path.parent.name}: {trial['score_error']}")
PY
}

run_stage course course
for cue in mm-hmm yeah; do
    run_stage "$cue" "$python" -m integrations.spoken_behavior_eval \
        --output "$out/$cue" --acknowledgment "$cue"
done
run_stage checkpoint "$python" -m integrations.spoken_behavior_eval \
    --output "$out/checkpoint" --scenario checkpoint
run_stage tts "$python" -m me3.tts_probe
run_stage simulator "$python" -m me3 benchmark --trials 20 --output "$out/simulator"
echo "Results: $out/status.tsv"
exit "$failed"
