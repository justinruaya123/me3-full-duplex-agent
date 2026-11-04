"""Secret-free deployment diagnostics; live probes are explicitly selected."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Mapping

from me3.configuration import ForegroundConfig
from me3.duplex_voice import settings


def configuration_report(env: Mapping[str, str]) -> dict:
    blockers = []
    foreground = None
    try:
        config = ForegroundConfig.from_env(env)
        foreground = {"profile": config.profile, "model": config.model}
    except ValueError:
        blockers.append("foreground")
    try:
        speech = settings(env)
        speech_models = {
            key: speech[key] for key in ("asr_model", "tts_model", "tts_voice")
        }
    except ValueError:
        speech_models = None
        blockers.append("speech")
    worker = {
        "provider": env.get("ME3_WORKER_PROVIDER") or None,
        "model": env.get("ME3_WORKER_MODEL") or None,
    }
    if not worker["model"] or not worker["provider"]:
        blockers.append("worker model/provider")
    if not env.get("ME3_WAKE_PHRASE"):
        blockers.append("wake phrase")
    if not env.get("ME3_SPEAKER_BASE_URL") or not env.get(
        "ME3_SPEAKER_API_KEY"
    ):
        blockers.append("speaker/overlap/addressee verification service")
    versions = {}
    for package in ("me3-full-duplex-agent", "pipecat-ai", "mcp", "httpx"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "ready": not blockers,
        "blockers": blockers,
        "foreground": foreground,
        "worker": worker,
        "speech": speech_models,
        "versions": versions,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "pi_binary": env.get("ME3_PI_BIN") or shutil.which("pi"),
        "qualification": {
            "acoustic": "not run",
            "raspberry_pi": "not run",
            "speakerphone_aec": "AEC3 implemented; physical qualification not run",
        },
    }


async def pi_rpc_probe() -> dict:
    """No prompt/inference: check installed CLI/protocol/model/tool policy."""
    from me3.harnesses import configured_backend

    backend = configured_backend()
    if not hasattr(backend, "_state"):
        raise ValueError("Pi RPC probe requires ME3_HARNESS=pi")
    root = (
        Path(os.environ.get("ME3_STATE_DIR", ".local/runtime"))
        / "rpc-probe/revision-1"
    )
    try:
        async with asyncio.timeout(20):
            await backend._ensure_process(root)
            await backend._state()
            return {
                "passed": True,
                "kind": "local RPC, no inference",
                "provider": backend.provider,
                "model": backend.model,
            }
    finally:
        await backend.close()


async def provider_probe() -> dict:
    from me3.foreground import ForegroundBackend
    from me3.harnesses import configured_backend

    config = ForegroundConfig.from_env(os.environ)
    foreground = ForegroundBackend(config)
    started = time.monotonic()
    text = await foreground.run(
        "Reply with ME3 ready.", Path("."), foreground=True
    )
    result = {
        "foreground": {
            "passed": bool(text.strip()),
            "seconds": time.monotonic() - started,
            "model": config.model,
            "reasoning_request": "disabled; no reasoning deltas observed",
        }
    }
    worker = configured_backend()
    try:
        started = time.monotonic()
        root = (
            Path(os.environ.get("ME3_STATE_DIR", ".local/runtime"))
            / "provider-probe/revision-1"
        )
        text = await worker.run(
            "Reply with ME3 ready. Do not use tools.", root
        )
        result["worker"] = {
            "passed": bool(text.strip()),
            "seconds": time.monotonic() - started,
        }
    finally:
        if hasattr(worker, "close"):
            await worker.close()
    return result


async def audio_probe() -> dict:
    """Device enumeration and real ONNX inference, without saving microphone audio."""
    import pyaudio

    from me3.capture import SmartTurn

    audio = pyaudio.PyAudio()
    try:
        devices = [
            audio.get_device_info_by_index(i)
            for i in range(audio.get_device_count())
        ]
        result = {
            "device_count": len(devices),
            "input_devices": sum(d["maxInputChannels"] > 0 for d in devices),
            "output_devices": sum(d["maxOutputChannels"] > 0 for d in devices),
            "capture": "not started; no recordings saved",
        }
    finally:
        audio.terminate()
    analyzer = SmartTurn()
    try:
        started = time.monotonic()
        complete = await analyzer(bytes(16000))
        result["smart_turn"] = {
            "seconds": time.monotonic() - started,
            "complete": complete,
            "input": "synthetic silence",
            "kind": "real ONNX runtime smoke, not behavioral scoring",
        }
    finally:
        await analyzer.close()
    return result


async def _main(args) -> dict:
    result = configuration_report(os.environ)
    for name, enabled, probe in (
        ("pi_rpc", args.pi_rpc, pi_rpc_probe),
        ("provider_inference", args.inference, provider_probe),
        ("audio_runtime", args.audio, audio_probe),
    ):
        if enabled:
            try:
                result[name] = await probe()
                if result[name].get("passed") is False or any(
                    isinstance(value, dict) and value.get("passed") is False
                    for value in result[name].values()
                ):
                    result["ready"] = False
                    result["blockers"].append(name)
            except Exception as exc:
                # Provider exceptions can include request URLs/credentials.
                result[name] = {
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "status": "blocked; inspect configuration, no fallback",
                }
                result["ready"] = False
                result["blockers"].append(name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pi-rpc",
        action="store_true",
        help="Local RPC/model check; no inference",
    )
    parser.add_argument(
        "--inference",
        action="store_true",
        help="Explicit real-provider model calls",
    )
    parser.add_argument(
        "--audio", action="store_true", help="Audio enumeration and ONNX smoke"
    )
    args = parser.parse_args()
    result = asyncio.run(_main(args))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()
