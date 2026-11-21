"""Three turns in one isolated live BMO Pi session with typed or digital speech input."""
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time


PROMPTS = (
    "Draft a three-step microphone soundcheck checklist in the background. Keep it under sixty words.",
    "What is seven plus five? Answer with just the number.",
    "Check the status of the soundcheck checklist I asked you to draft.",
)


def assess(turns):
    submitted, answer, returned = turns
    jobs = submitted["tools"]
    receipts = returned["tools"]
    delegated = (len(jobs) == 1 and jobs[0].get("name") == "delegate_task"
                 and bool(jobs[0].get("id")) and jobs[0].get("revision") == 1
                 and jobs[0].get("status") in {"queued", "running", "completed"})
    return dict(
        delegated_once=delegated,
        direct_answer=not answer["tools"] and bool(re.fullmatch(
            r"(12|twelve)[.!]?", answer["text"].strip(), flags=re.IGNORECASE)),
        same_job=delegated and len(receipts) == 1 and receipts[0].get("name") == "delegated_task_status"
        and receipts[0].get("id") == jobs[0]["id"]
        and receipts[0].get("revision") == jobs[0]["revision"]
        and receipts[0].get("status") in {"queued", "running", "completed"},
    )


def microphone_transcript(event):
    msg = event.get("message", {})
    if event.get("type") != "message_start" or msg.get("role") != "user":
        return None
    content = msg.get("content", [])
    text = content if isinstance(content, str) else " ".join(
        block["text"] for block in content if block.get("type") == "text")
    prefix = "Microphone transcript: "
    return text[len(prefix):] if text.startswith(prefix) else None


def read_result(event, row):
    if event.get("type") == "tool_execution_end":
        details = event.get("result", {}).get("details") or {}
        row["tools"].append({"name": event["toolName"], "failed": bool(event.get("isError")),
                             **{k: details[k] for k in ("id", "revision", "status") if k in details}})
    elif event.get("type") == "message_end":
        message = event.get("message", {})
        if message.get("role") == "assistant":
            if message.get("stopReason") == "error":
                row["error"] = "Foreground provider error"
            row["text"] = " ".join(b["text"] for b in message["content"] if b["type"] == "text")


async def turn(pi, prompt, row):
    start = time.monotonic()
    pi.stdin.write((json.dumps({"type": "prompt", "message": prompt}) + "\n").encode())
    await pi.stdin.drain()
    while line := await pi.stdout.readline():
        event = json.loads(line)
        read_result(event, row)
        if event.get("type") == "agent_settled":
            row["seconds"] = round(time.monotonic() - start, 3)
            return
    raise ValueError("Pi exited before the routing turn settled")


async def collect_spoken(pi, report):
    current = None
    while line := await pi.stdout.readline():
        event = json.loads(line)
        rows = report["turns"]
        transcript = microphone_transcript(event)
        if transcript and rows:
            current = rows[-1]
            current["transcripts"].append(transcript)
        if current is not None:
            read_result(event, current)
            if event.get("type") == "agent_settled":
                current = None
        if event.get("notifyType") == "error" and rows:
            message = event.get("message", "").lower()
            rows[-1]["device_error"] = ("digital capture overrun" if "overrun" in message
                                        else "Pi or audio device reported an error")


async def start_device(pi):
    pi.stdin.write(b'{"type":"prompt","message":"/me3 duplex"}\n')
    await pi.stdin.drain()


async def evaluate(root, output, env_file, thinking, *, rig=None, fdbench=None):
    report = {"kind": "live Pi.dev typed routing, isolated chat, microphone closed", "turns": []}
    clips = []
    if rig:
        import numpy as np
        import soxr
        from me3 import bmo
        model = Path(os.environ.get("ME3_BMO_DIR", bmo.ROOT))
        if not all(bmo.verify(model / name) for name in bmo.PINS):
            raise ValueError("BMO voice checksum mismatch")
        render = bmo.renderer(model)
        for prompt in PROMPTS:
            pcm = np.frombuffer(render(prompt), dtype="<i2").astype(np.float32) / 32768
            clips.append(soxr.resample(pcm, 24000, 16000))
        report["kind"] = "live Pi.dev routing with synthesized speech over the class digital audio rig"
    with tempfile.TemporaryDirectory(prefix="me3-routing-") as client:
        env = dict(os.environ, ME3_CLIENT_HOME=client, VOICECHAT_PYTHON=sys.executable,
                   ME3_BENCH_ENV_FILE=str(Path(env_file).resolve()), ME3_MEMORY_ENABLED="0",
                   ME3_FOREGROUND_THINKING=thinking, ME3_VOICE_TTS="bmo",
                   ME3_VOICE_PROMPT_DIR=str(root / "integrations/voicechat/templates"),
                   ME3_BENCH_LOG_DIR=str(output / "pi"))
        if rig:
            env.update(ME3_FDBENCH_URL=rig.url, PYTHONPATH=os.pathsep.join((str(root), str(fdbench / "adapters"))))
        with (output / "launcher.log").open("w") as log:
            pi = await asyncio.create_subprocess_exec(
                "bash", "integrations/voicechat/start.sh", "--live-benchmark", "--terminal",
                "--mode", "rpc", "--no-session", "--tools", "delegate_task,delegated_task_status",
                cwd=root, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=log, limit=1024 * 1024)
            reader = None
            try:
                if rig:
                    await start_device(pi)
                    async with asyncio.timeout(60):
                        while line := await pi.stdout.readline():
                            if json.loads(line).get("statusText") == "Deepgram + Pi + BMO Piper · fdbench":
                                break
                        else:
                            raise ValueError("Pi exited before the BMO digital audio device was ready")
                    reader = asyncio.create_task(collect_spoken(pi, report))
                for i, prompt in enumerate(PROMPTS):
                    row = {"prompt": prompt, "tools": [], "text": ""}
                    report["turns"].append(row)
                    async with asyncio.timeout(90):
                        if rig:
                            import soundfile as sf
                            from fdbench.rig.base import TrialScript
                            row["transcripts"] = []
                            sf.write(output / f"turn-{i+1}-input.wav", clips[i], 16000)
                            if not rig.connected.is_set():
                                await start_device(pi)
                                row["reconnected"] = await asyncio.to_thread(rig.wait_for_assistant, 20)
                                if not row["reconnected"]:
                                    row["error"] = "Digital audio did not reconnect"
                                    continue
                            try:
                                recording = await asyncio.to_thread(rig.run, TrialScript(
                                    play_first=clips[i], record_after=12, max_duration=28))
                            except RuntimeError as exc:
                                row["error"] = str(exc)
                                continue
                            sf.write(output / f"turn-{i+1}-reply.wav", recording.heard, 16000)
                            row["recorded_speech"] = bool(recording.bot_starts)
                        else:
                            await turn(pi, prompt, row)
                report["checks"] = assess(report["turns"])
                if rig:
                    report["checks"]["three_spoken_turns"] = all(
                        len(r["transcripts"]) == 1 and r.get("recorded_speech") and not r.get("error")
                        for r in report["turns"])
                if not all(report["checks"].values()):
                    raise ValueError("Live Pi routing checks failed")
            finally:
                if reader:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                (output / "routing.json").write_text(json.dumps(report, indent=2) + "\n")
                pi.stdin.close()
                try:
                    await asyncio.wait_for(pi.wait(), 10)
                except TimeoutError:
                    pi.kill()
                    await pi.wait()
