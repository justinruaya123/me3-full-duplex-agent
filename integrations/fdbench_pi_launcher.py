"""Launch one real, isolated Pi RPC session for the course reset controller."""
import argparse
import json
import os
import re
import signal
import time
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--wait", type=float)
    args = parser.parse_args()
    root = args.project
    plugin = root / "integrations/voicechat"
    from fdbench_marks import mark

    # Keep the evaluation out of the operator's profile, memory and task queue.
    model = "deepseek/deepseek-v4.1-flash"
    env = dict(os.environ, ME3_FDBENCH_URL=args.url, ME3_VOICE_TTS="bmo", ME3_LIVE_BENCHMARK="1",
               ME3_FOREGROUND_MODEL=model, ME3_MEMORY_ENABLED="0", ME3_BENCH_LOG_DIR=str(args.log_dir),
               ME3_VOICE_PROMPT_DIR=str(plugin / "templates"),
               PI_CODING_AGENT_DIR=str(args.log_dir / "pi"),
               VOICECHAT_PYTHON=sys.executable)
    env.pop("ME3_CLIENT_HOME", None)
    cmd = [str(plugin / "node_modules/.bin/pi"), "--mode", "rpc", "--no-session",
           "--no-context-files", "--no-extensions", "--no-skills", "--no-prompt-templates",
           "--tools", "show_dashboard,update_dashboard", "--extension", str(plugin / "pi.mjs"),
           "--extension", str(plugin / "nitro.mjs"), "--provider", "openrouter",
           "--model", model, "--thinking", os.environ["ME3_FDBENCH_THINKING"],
           "--system-prompt", "You are the ME3 voice assistant in the current Pi chat."]
    with subprocess.Popen(cmd, env=env, cwd=args.log_dir, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as pi:
        def log_error(source, detail):
            detail = detail if isinstance(detail, str) else ""
            status = re.search(r"\b([45]\d\d)\b", detail)
            reason = "request failed"
            for signature, classification in (
                ("reasoning is mandatory", "reasoning required"),
                ("digital capture overrun", "digital capture overrun"),
                ("timed out", "timeout"),
                ("disconnected", "transport disconnected"),
                ("playback failed", "playback failed"),
            ):
                if signature in detail.lower():
                    reason = classification
                    break
            with (args.log_dir / "errors.jsonl").open("a") as log:
                print(json.dumps(dict(source=source, at=time.monotonic(), reason=reason,
                                      http=int(status[1]) if status else None)), file=log)


        # Pi's RPC stdin EOF runs session_shutdown, flushes audio, and reaps
        # its sidecar before this process exits.
        stopping = False

        def stop(_sig, _frame):
            nonlocal stopping
            stopping = True
            pi.stdin.close()

        signal.signal(signal.SIGTERM, stop)
        try:
            pi.stdin.write(json.dumps({"type": "prompt", "message": "/me3 duplex"}) + "\n")
            pi.stdin.flush()
            ready = False
            first_token = False
            for line in pi.stdout:
                event = json.loads(line)
                status = event.get("statusText", "")
                if status == "Deepgram + Pi + BMO Piper · fdbench":
                    ready = True
                    print(f"connected to fdbench at {args.url} · benchmark mode", flush=True)
                elif ready and status.endswith(" · off"):
                    print("fdbench closed the connection: run over, shutting the assistant down",
                          flush=True)
                    return
                elif event.get("notifyType") == "error" or event.get("success") is False:
                    log_error("pi", event.get("message") or event.get("error") or "No detail")
                    if not ready:
                        raise RuntimeError("Pi failed during startup; see errors.jsonl")
                elif event.get("type") == "message_start":
                    first_token = False
                elif (event.get("assistantMessageEvent", {}).get("type") == "text_delta"
                      and not first_token):
                    first_token = True
                    mark("llm_first_token")
                elif (event.get("type") == "message_end" and isinstance(event.get("message"), dict)
                      and event["message"].get("stopReason") == "error"):
                    # A rejected reply is a measured missing reply. Keep the
                    # transport alive for the rest of this recording and reset.
                    log_error("foreground", event["message"].get("errorMessage"))
            if not stopping:
                raise RuntimeError("Pi exited before the benchmark transport closed")
        finally:
            if not stopping:
                pi.terminate()


if __name__ == "__main__":
    main()
