#!/usr/bin/env bash
# Benchmark the project-local Pi voice agent with the real BMO speech profile.
set -euo pipefail
umask 077
cd "$(dirname "$0")"
if [[ ${1-} == --legacy ]]; then shift; exec ./scripts/legacy-benchmark.sh "$@"; fi
if [[ ${1-} == --smoke ]]; then
    shift
    set -- all --rounds 1 --phrases 3 --runs 1 "$@"
fi
client="$PWD"
if common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
    client=$(dirname "$common")
fi
runtime=.venv313
if [[ $(uname -s) == Linux ]]; then runtime=.venv-pi; fi
python=${VOICECHAT_PYTHON:-"${ME3_CLIENT_HOME:-$client}/$runtime/bin/python"}
if [[ ! -x "$python" ]]; then
    echo 'Set VOICECHAT_PYTHON to the installed BMO voice environment.' >&2
    exit 2
fi
if [[ ${1-} == cues || ${1-} == --help || ${1-} == -h ]]; then
    exec "$python" benchmark.py "$@"
fi
if ! command -v expect >/dev/null; then
    if [[ -t 0 && -t 1 ]]; then exec "$python" benchmark.py "$@"; fi
    echo 'Install expect for unattended class runs (the scorer pauses after five missed replies).' >&2
    exit 2
fi
# Keep every missed reply in the score. Answer only the upstream silence prompt.
TERM=xterm exec expect -f - "$python" "$@" <<'TCL'
set timeout -1
spawn -noecho [lindex $argv 0] -u benchmark.py {*}[lrange $argv 1 end]
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
