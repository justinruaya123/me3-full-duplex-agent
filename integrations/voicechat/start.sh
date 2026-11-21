#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/../.."
if [[ -x "$PWD/.local/node/bin/node" ]]; then export PATH="$PWD/.local/node/bin:$PATH"; fi
# Use the ME3 installation shared by linked worktrees, or this checkout after transfer.
client="${ME3_CLIENT_HOME:-$PWD}"
if [[ -z "${ME3_CLIENT_HOME:-}" && "$(git rev-parse --show-toplevel 2>/dev/null || true)" == "$(pwd -P)" ]]; then
    common=$(git rev-parse --path-format=absolute --git-common-dir)
    client=$(dirname "$common")
fi
boot_error() {
    printf 'BMO setup: %s\n' "$2" >&2
    if [[ -t 1 || "$boot_window" == 1 ]]; then
        local clip="$PWD/integrations/voicechat/behavior/startup/$1.wav"
        if command -v afplay >/dev/null; then afplay "$clip" >&2 || true
        elif command -v aplay >/dev/null; then aplay -q "$clip" >&2 || true
        fi
    fi
    exit 1
}
boot_window=0
[[ " $* " == *" --window "* ]] && boot_window=1
memory_override="${ME3_MEMORY_ENABLED-}"
if [[ -f "$client/.env" ]]; then
    set -a
    source "$client/.env"
    set +a
fi
export ME3_MEMORY_ENABLED="${memory_override:-${ME3_MEMORY_ENABLED:-1}}"
cli="$PWD/integrations/voicechat/node_modules/.bin/pi"
if ! command -v node >/dev/null; then boot_error setup "Install Node and npm for this device."; fi
if [[ ! -x "$cli" || ! -r "$PWD/integrations/voicechat/node_modules/@arcanemachine/pi-web-search/index.ts" ]]; then
    [[ -r "$PWD/integrations/voicechat/package.json" ]] || boot_error setup "Missing project Pi package manifest."
    npm ci --prefix "$PWD/integrations/voicechat" --no-audit --no-fund >&2 || boot_error setup "Install Node and npm, then rerun the project launcher."
fi
runtime_python="$client/.venv313/bin/python"
if [[ "$(uname -s)" == Linux ]]; then runtime_python="$client/.venv-pi/bin/python"; fi
export VOICECHAT_PYTHON="${VOICECHAT_PYTHON:-$runtime_python}"
export ME3_KOKORO_DIR="${ME3_KOKORO_DIR:-.local/models/kokoro-int8-multi-lang-v1_0}"
[[ "$ME3_KOKORO_DIR" == /* ]] || export ME3_KOKORO_DIR="$client/$ME3_KOKORO_DIR"
session_tools=read_trial_brief,create_website,delegate_task,delegated_task_status
if [[ "${1:-}" == --live-benchmark ]]; then
    shift
    session_tools=delegate_task,delegated_task_status,create_website
    bench_env="${ME3_BENCH_ENV_FILE:-.local/benchmark.env}"
    if [[ -f "$bench_env" ]]; then
        set -a
        source "$bench_env"
        set +a
    fi
    export ME3_FOREGROUND_THINKING="${ME3_FOREGROUND_THINKING:-off}"
    export ME3_LIVE_BENCHMARK=1
    export ME3_FOREGROUND_PROVIDER=openrouter ME3_WORKER_PROVIDER=openrouter
    export ME3_FOREGROUND_MODEL=deepseek/deepseek-v4.1-flash ME3_WORKER_MODEL=deepseek/deepseek-v4.1-flash
    export ME3_WORKER_API_KEY_ENV=OPENROUTER_API_KEY
    export ME3_PIPER_DIR="${ME3_PIPER_DIR:-$PWD/.local/models/vits-piper-en_US-lessac-medium-int8}"
fi
# Pin the project profile after loading the benchmark profile, including for worker subprocesses.
export ME3_CLIENT_HOME="$(cd "$client" && pwd -P)"
export PI_CODING_AGENT_DIR="$ME3_CLIENT_HOME/.local/pi"
unset PI_CODING_AGENT_SESSION_DIR PI_PACKAGE_DIR
node integrations/voicechat/project.mjs "${1:-}" ||
    boot_error trust "Check access to this project's .local/pi. An explicit denial can be changed with --trust-project."
if [[ "${1:-}" == --trust-project ]]; then exit 0; fi
if [[ ! -x "$VOICECHAT_PYTHON" ]]; then boot_error setup "Install the project Python environment or set VOICECHAT_PYTHON."; fi
if [[ "${1:-}" != --sanity ]]; then
    if [[ "${ME3_FOREGROUND_PROVIDER:-}" == openrouter || "${ME3_WORKER_PROVIDER:-}" == openrouter ]]; then
        [[ -n "${OPENROUTER_API_KEY:-}" ]] || boot_error setup "Set OPENROUTER_API_KEY in the private project environment."
    fi
    if [[ "${ME3_ASR_BACKEND:-}" == deepgram || "${ME3_LIVE_BENCHMARK:-0}" == 1 ]]; then
        [[ -n "${DEEPGRAM_API_KEY:-}" ]] || boot_error setup "Set DEEPGRAM_API_KEY in the private project environment."
    fi
fi
export ME3_VOICE_TTS="${ME3_VOICE_TTS:-bmo}"
case "$ME3_VOICE_TTS" in
    bmo)
        export ME3_BMO_DIR="${ME3_BMO_DIR:-$PWD/.local/models/bmo-v1.0-voice}"
        bash scripts/setup-bmo.sh >&2 || boot_error setup "BMO voice setup failed. Check the asset or dependency reported above." ;;
    lessac)
        export ME3_PIPER_DIR="${ME3_PIPER_DIR:-$PWD/.local/models/vits-piper-en_US-lessac-medium-int8}"
        [[ -r "$ME3_PIPER_DIR/en_US-lessac-medium.onnx" ]] || boot_error setup "Missing Lessac voice at $ME3_PIPER_DIR." ;;
    kokoro) ;;
    *) boot_error setup "Choose ME3_VOICE_TTS=bmo, lessac, or kokoro." ;;
esac
session_tools+=",subagent,revise_delegated_task,web_lookup,recall_web_search,portfolio_research,show_dashboard,update_dashboard,remember_detail"
export ME3_VOICE_PROMPT_DIR="${ME3_VOICE_PROMPT_DIR:-$PWD/.local/voice-prompts}"
# Seed optional editing guides on first launch and preserve operator edits.
(
    umask 077
    mkdir -p "$ME3_VOICE_PROMPT_DIR"
    for section in SYSTEM SOUL USER WORKER; do
        file="$ME3_VOICE_PROMPT_DIR/$section.md"
        if [[ ! -e "$file" ]]; then
            cp -n "$PWD/integrations/voicechat/templates/$section.md" "$file"
        fi
    done
)
export ME3_WORKER_THINKING="${ME3_WORKER_THINKING:-high}"
thinking="${ME3_FOREGROUND_THINKING:-low}"
provider="${ME3_FOREGROUND_PROVIDER:-}"
model="${ME3_FOREGROUND_MODEL:-}"
[[ -n "$provider" && -n "$model" ]] || boot_error setup "Set ME3_FOREGROUND_PROVIDER and ME3_FOREGROUND_MODEL, or select --live-benchmark."
if [[ "${1:-}" == --sanity ]]; then
    if ! "$VOICECHAT_PYTHON" - <<'PYTHON'
import asyncio
import aiohttp
import soxr
from me3.doctor import audio_probe

audio = asyncio.run(audio_probe())
print("Audio devices:", audio["input_devices"], "inputs,", audio["output_devices"], "outputs; Smart Turn processed synthetic silence")
if not (audio["input_devices"] and audio["output_devices"]):
    raise SystemExit("Connect a microphone and speaker, and check device access.")
PYTHON
    then boot_error setup "Check the project voice dependencies, microphone and output device."; fi
    echo "Project Pi $("$cli" --version) · $cli"
    node --input-type=module -e 'import {workflows,roleNames} from "./integrations/voicechat/subagents.mjs"; console.log("Superpowers:", workflows.length, "workflows; subagents:", roleNames.join(", "))'
    echo "Foreground $provider/$model · voice $ME3_VOICE_TTS"
    if [[ -n "${BRAVE_SEARCH_API_KEY:-}" ]]; then echo "Brave key configured"; else echo "Brave lookup unavailable: set BRAVE_SEARCH_API_KEY"; fi
    if [[ "${ME3_ASR_BACKEND:-}" == deepgram && -z "${DEEPGRAM_API_KEY:-}" ]]; then echo "Deepgram key missing. Run python3 setup.py configure." >&2; exit 1; fi
    if [[ "$provider" == openrouter && -z "${OPENROUTER_API_KEY:-}" ]]; then echo "OpenRouter key missing. Run python3 setup.py configure." >&2; exit 1; fi
    exit 0
fi
window=0
if [[ "${1:-}" == --window ]]; then window=1; shift
elif [[ "${1:-}" == --terminal ]]; then shift
elif [[ -t 0 && -t 1 && " $* " != *" --mode "* && " $* " != *" --print "* && " $* " != *" -p "* ]]; then window=1
fi
if [[ "$window" == 1 ]]; then
    bash scripts/setup-openintelligentui.sh >&2
    "$VOICECHAT_PYTHON" integrations/voicechat/theme/install-pi.py "$PI_CODING_AGENT_DIR" || boot_error setup "Install the project window dependencies or run with --terminal."
    session_tools+=",show_visual,focus_panel"
fi
extensions=(--extension "$PWD/integrations/voicechat/pi.mjs")
if [[ "${ME3_LIVE_BENCHMARK:-0}" == 1 || "$provider/$model" == openrouter/deepseek/deepseek-v4.1-flash ]]; then
    extensions+=(--extension "$PWD/integrations/voicechat/nitro.mjs")
elif [[ "$provider/$model" == openai-codex/gpt-6-luna && "$thinking" == off ]]; then
    extensions+=(--extension "$PWD/integrations/voicechat/luna.mjs")
fi
runner=("$cli")
if [[ "$window" == 1 ]]; then runner=("$VOICECHAT_PYTHON" -m integrations.voicechat.window "$cli"); fi
exec "${runner[@]}" --no-extensions --no-skills --skill "$PWD/.agents/skills/conversational-ux" \
    --skill "$PWD/integrations/voicechat/skills" --skill "$PWD/integrations/voicechat/vendor/superpowers/skills" --no-context-files --no-prompt-templates \
    --tools "$session_tools" "${extensions[@]}" --provider "$provider" --model "$model" --thinking "$thinking" \
    --system-prompt "You are the ME3 voice assistant in the current Pi chat." "$@"
