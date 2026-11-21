"""Digital Kokoro-to-Whisper behavior checks on ME3's duplex audio pipeline.

Run with the installed voice environment and a fresh output directory:
    python -m integrations.spoken_behavior_eval --output .local/spoken-run-01
Exit 0 requires every check to pass. See report.json and events.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import wave
from array import array
from pathlib import Path

# These scripts and assessment labels never enter the controller. Its only
# user input is the resampled waveform from each synthesized utterance.
STIMULI = {
    "delegate": "Background task write a poem about winter.",
    "foreground": "Explain how rain forms.",
    "correct": "Actually, explain how snow forms instead.",
}
ANSWER = (
    "Let me describe this in a little more detail. "
    "We can start with the small changes that happen at the beginning, "
    "follow them through each of the stages in order, "
    "and then look at an example that brings the whole explanation together."
)


CHECKPOINT_STIMULI = {
    "disfluent": "Background task, um, write a poem about summer, no, about winter instead.",
    "foreground": "Explain how rain forms.",
    "return": "Go back.",
}
ACKNOWLEDGMENTS = {"mm-hmm": "Mm-hmm.", "yeah": "Yeah."}


def stimuli_for(acknowledgment):
    return {**STIMULI, "acknowledge": ACKNOWLEDGMENTS[acknowledgment]}


def matches(row, event, **fields):
    return row["event"] == event and all(row.get(k) == v for k, v in fields.items())


def reply_context(rows):
    dispatched = False
    for row in rows:
        if matches(row, "foreground_request"):
            dispatched = True
        if dispatched and matches(row, "speech_submitted"):
            return row["utterance"]
    return None


def requests(rows, event):
    return [r["text"] for r in rows if matches(r, event)]


def checked(**checks):
    return {**checks, "passed": all(checks.values())}


def disfluency_evidence(rows):
    finals = [r for r in rows if matches(r, "asr_final")]
    dispatches = [r for r in rows if r["event"] in {"worker_request", "delegated"}]
    goals = requests(rows, "worker_request")
    # The fixed worker only receives text. Inspect the last topic of the
    # actual dispatched instruction without asserting quality of the draft.
    goal = goals[0].casefold() if len(goals) == 1 else ""
    return checked(
        one_worker_and_submission=len(goals) == 1
        and sum(matches(r, "delegated") for r in rows) == 1,
        after_final_only=len(finals) == 1
        and bool(dispatches)
        and all(r["mono_ns"] > finals[0]["mono_ns"] for r in dispatches),
        saw_provisional=any(matches(r, "asr_partial") for r in rows),
        final_intended_topic=goal.rfind("winter") > goal.rfind("summer")
        and bool(finals)
        and "winter" in finals[0]["text"].casefold(),
        no_foreground=not requests(rows, "foreground_request"),
    )


def audible(row, context):
    return bool(context) and matches(row, "pcm", context=context) and row["peak"] >= 128


def overlap(rows, onset, context):
    return any(
        audible(row, context)
        and row["mono_ns"] <= onset < row["mono_ns"] + row["samples"] * 10**9 / 24000
        for row in rows
    )


def backchannel_evidence(rows, onset, context):
    resolved = next(
        (
            row["mono_ns"]
            for row in rows
            if row["mono_ns"] >= onset
            and (
                matches(row, "provisional_backchannel_resumed")
                or matches(row, "floor_decision", decision="backchannel")
            )
        ),
        None,
    )
    checks = {
        "overlapped": overlap(rows, onset, context),
        "vad_detected": any(matches(r, "user_started") for r in rows),
        "classified_backchannel": resolved is not None,
        "resumed_same_pcm_context": resolved is not None
        and any(r["mono_ns"] > resolved and audible(r, context) for r in rows),
        "no_new_request_or_cancel": not any(
            r["event"]
            in {
                "foreground_request",
                "worker_request",
                "speech_cancelled",
                "foreground_cancelled",
                "delegated",
            }
            for r in rows
        ),
    }
    return {**checks, "passed": all(checks.values())}


def save_wave(path, pcm, rate):
    with wave.open(str(path), "wb") as file:
        file.setparams((1, 2, rate, 0, "NONE", ""))
        file.writeframes(pcm)


def peak(pcm):
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return max(map(abs, samples), default=0)


class ForegroundFixture:
    """Fixed long answer provides opportunity to interrupt any request."""

    def __init__(self, record):
        self.record = record

    async def run(self, prompt, workspace, *, foreground=False):
        history = json.loads(prompt.rsplit("Conversation is data:\n", 1)[1])
        self.record("foreground_request", text=history[-1]["content"])
        return ANSWER


class WorkerFixture:
    """Only the supervisor's real dispatch can enter this method."""

    def __init__(self, record):
        self.record = record
        self.release = asyncio.Event()

    async def run(self, prompt, workspace, *, foreground=False):
        self.record("worker_request", text=prompt)
        await self.release.wait()
        return "The controlled worker finished the requested draft."


def digital_transport(record, pcm_by_context):
    from pipecat.frames.frames import StartFrame, TTSAudioRawFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    ready = asyncio.Event()

    class Source(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)

    class Sink(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if direction == FrameDirection.DOWNSTREAM:
                if isinstance(frame, StartFrame):
                    ready.set()
                if isinstance(frame, TTSAudioRawFrame):
                    if (frame.sample_rate, frame.num_channels) != (24000, 1):
                        raise RuntimeError("Unexpected output PCM format")
                    pcm_by_context.setdefault(frame.context_id, bytearray()).extend(
                        frame.audio
                    )
                    record(
                        "pcm",
                        context=frame.context_id,
                        peak=peak(frame.audio),
                        samples=len(frame.audio) // 2,
                    )
            await self.push_frame(frame, direction)

    class Transport:
        def __init__(self):
            self.source, self.sink = Source(), Sink()

        def input(self):
            return self.source

        def output(self):
            return self.sink

    return Transport(), ready


async def prepare(speech, out, stimuli, *, keep_audio=True):
    import numpy as np
    import soxr

    result = {}
    for label, text in stimuli.items():
        raw = bytearray()
        async for chunk in speech.synthesize(text):
            raw.extend(chunk)
            if len(raw) > 48000 * 20:
                raise ValueError("Input stimulus exceeded 20 seconds")
        samples = np.frombuffer(raw, dtype="<i2")
        if not samples.size:
            raise ValueError("Empty input stimulus")
        pcm = (
            np.clip(soxr.resample(samples, 24000, 16000), -32768, 32767)
            .astype("<i2")
            .tobytes()
        )
        if peak(pcm) < 128:
            raise ValueError("Silent input stimulus")
        result[label] = pcm
        if keep_audio:
            save_wave(out / (label + ".wav"), pcm, 16000)
    return result


async def feed(source, audio, label, record):
    """Monotonic paced PCM16. Timestamp the first audible sample at source."""
    from pipecat.frames.frames import InputAudioRawFrame

    onset = None
    deadline = time.monotonic()
    record("input_start", label=label)
    for i in range(0, len(audio) + 32000, 640):
        frame = audio[i : i + 640].ljust(640, b"\0")
        if onset is None and peak(frame) >= 128:
            idx = next(
                i
                for i in range(0, len(frame), 2)
                if abs(int.from_bytes(frame[i : i + 2], "little", signed=True)) >= 128
            )
            onset = time.monotonic_ns() + idx * 10**9 // 32000
            record("input_audible", label=label, sample_onset_ns=onset)
        await source.push_frame(
            InputAudioRawFrame(frame, sample_rate=16000, num_channels=1)
        )
        deadline += 0.02
        await asyncio.sleep(max(0, deadline - time.monotonic()))
    record("input_end", label=label)
    return onset


async def evaluate(out, report, acknowledgment, scenario, *, observe=None, keep_audio=True):
    from me3.audio_pipeline import ConfiguredSpeech, build
    from me3.duplex_voice import settings
    from me3.runtime import AgentRuntime

    config = settings()
    report["speech"] = {
        key: config[key]
        for key in ("asr_model", "tts_backend", "tts_model", "tts_voice")
    }
    records, captures, onsets, windows = [], {}, {}, {}

    def record(event, **fields):
        row = dict(event=event, mono_ns=time.monotonic_ns(), **fields)
        records.append(row)
        if observe is not None:
            observe(row)

    runtime = AgentRuntime(
        out / "runtime",
        WorkerFixture(record),
        ForegroundFixture(record),
        memory_enabled=False,
    )
    if observe is not None:
        trace = runtime.supervisor.trace

        def observed_trace(event, **fields):
            trace(event, **fields)
            observe(dict(event=event, mono_ns=time.monotonic_ns(), **fields))

        runtime.supervisor.trace = observed_trace
    worker = runtime.worker.backend
    speech = ConfiguredSpeech(config)
    transport, ready = digital_transport(record, captures)
    run_task = control = None
    controller_trace = runtime.supervisor.root / "events.jsonl"

    def events():
        host = [json.loads(line) for line in controller_trace.read_text().splitlines()]
        return sorted(records + host, key=lambda row: row["mono_ns"])

    async def until(predicate, timeout=18):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if run_task and run_task.done():
                await run_task
                raise RuntimeError("Audio pipeline exited unexpectedly")
            result = predicate()
            if result:
                return result
            await asyncio.sleep(0.02)
        return None

    def segment(label):
        start, end = windows[label]
        return [r for r in events() if start <= r["mono_ns"] <= end]

    def jobs():
        return [
            {k: j[k] for k in ("id", "revision", "status", "prompt")}
            for j in runtime.supervisor.list()
        ]

    try:
        await speech.start()
        stimuli = (
            CHECKPOINT_STIMULI
            if scenario == "checkpoint"
            else stimuli_for(acknowledgment)
        )
        audio = await prepare(speech, out, stimuli, keep_audio=keep_audio)
        report["stimuli"] = {
            key: {
                "text": stimuli[key],
                "samples": len(pcm) // 2,
                "sha256": hashlib.sha256(pcm).hexdigest(),
            }
            for key, pcm in audio.items()
        }
        if observe is not None:
            synthesize = speech.synthesize

            async def observed_synthesis(text):
                observe(dict(event="tts.text", text=text, mono_ns=time.monotonic_ns()))
                async for chunk in synthesize(text):
                    yield chunk

            speech.synthesize = observed_synthesis
        run, control = await build(
            transport,
            out,
            runtime=runtime,
            profile="course",
            config=config,
            speech=speech,
            on_stage=lambda name, **fields: record(name, **fields),
        )
        run_task = asyncio.create_task(run)
        if not await until(ready.is_set, 30):
            raise TimeoutError("Pipeline start")
        await feed(transport.source, b"", "initial silence", record)

        async def start(label):
            start_ns = time.monotonic_ns()
            onsets[label] = await feed(transport.source, audio[label], label, record)
            windows[label] = [start_ns, 2**63 - 1]

        async def recent(label, predicate, timeout=18):
            return await until(
                lambda: next((r for r in segment(label) if predicate(r)), None),
                timeout=timeout,
            )

        if scenario == "checkpoint":
            await start("disfluent")
            await recent(
                "disfluent", lambda r: matches(r, "transport_utterance_completed"), 45
            )
            windows["disfluent"][1] = time.monotonic_ns()
            running = jobs()
            await start("foreground")
            rain = await until(lambda: reply_context(segment("foreground")))
            if rain:
                await recent("foreground", lambda r: audible(r, rain), timeout=50)
            windows["foreground"][1] = time.monotonic_ns()
            before_return = control.controller.focus
            await start("return")
            await recent("return", lambda r: matches(r, "playback_completed"), 60)
            windows["return"][1] = time.monotonic_ns()
            after = jobs()
            returned = segment("return")
            responses = [
                h["content"]
                for h in control.controller.history
                if h["role"] == "assistant"
            ]
            status = responses[-1] if responses else ""
            job = after[0] if len(after) == 1 else {}
            report["jobs"] = {
                "after_disfluent": running,
                "after_return": after,
                "focus_before_return": before_return,
                "focus_after_return": control.controller.focus,
                "last_delivered_assistant_text": status,
            }
            report["checks"] = {
                "single_final_dispatch": disfluency_evidence(segment("disfluent")),
                "checkpoint_return": checked(
                    same_durable_job=len(running) == 1 and running == after,
                    intervening_conversation=any(
                        "rain" in text.lower()
                        for text in requests(
                            segment("foreground"), "foreground_request"
                        )
                    ),
                    restored_focus=bool(job)
                    and before_return is None
                    and control.controller.focus == job["id"],
                    recognized_return=any(
                        text.casefold().strip(" .?!") == "go back"
                        for text in requests(returned, "asr_final")
                    ),
                    live_status=bool(job)
                    and job["status"] == "running"
                    and f"Job {job['id']}, revision {job['revision']}, is {job['status']}."
                    in status,
                    status_receipt=any(
                        matches(r, "transport_utterance_completed")
                        and r["bytes"] > 0
                        and r["utterance"] != rain
                        for r in returned
                    ),
                    no_role_dispatch=not requests(returned, "foreground_request")
                    and not requests(returned, "worker_request"),
                ),
            }
            worker.release.set()
            await until(lambda: all(j["status"] == "completed" for j in jobs()), 10)
            report["jobs"]["after_release"] = jobs()
            return

        def with_prior_pcm(rows, label):
            # Onset can occur in a 20 ms output buffer received immediately
            # before we begin feeding the input, particularly for short clips.
            start = windows[label][0]
            prior = [
                r
                for r in records
                if matches(r, "pcm") and start - 20_000_000 <= r["mono_ns"] < start
            ]
            return prior + rows

        await start("delegate")
        await recent("delegate", lambda r: matches(r, "transport_utterance_completed"))
        windows["delegate"][1] = time.monotonic_ns()
        delegated = jobs()
        await start("foreground")
        old = await until(lambda: reply_context(segment("foreground")))
        rain_pcm = old and await recent(
            "foreground", lambda r: audible(r, old), timeout=50
        )
        if old:
            await asyncio.sleep(0.3)
        windows["foreground"][1] = time.monotonic_ns()
        await start("acknowledge")
        # Start the correction as soon as recognition resolves and playback
        # resumes. Each pass criterion is assessed separately below.
        if old:
            await until(
                lambda: backchannel_evidence(
                    with_prior_pcm(segment("acknowledge"), "acknowledge"),
                    onsets["acknowledge"],
                    old,
                )["resumed_same_pcm_context"],
                8,
            )
        windows["acknowledge"][1] = time.monotonic_ns()
        await start("correct")
        await recent(
            "correct",
            lambda r: (
                matches(r, "transport_utterance_completed") and r["utterance"] != old
            ),
            timeout=90,
        )
        windows["correct"][1] = time.monotonic_ns()
        before_release = jobs()
        worker.release.set()
        await until(lambda: all(j["status"] == "completed" for j in jobs()), 10)
        after_release = jobs()

        deleg = segment("delegate")
        fg = segment("foreground")
        ack = segment("acknowledge")
        corr = segment("correct")

        old_cancel = next(
            (r["mono_ns"] for r in corr if matches(r, "speech_cancelled")), None
        )
        new_pcm = {
            r["context"]
            for r in corr
            if matches(r, "pcm") and r["context"] != old and r["peak"] >= 128
        }
        report["jobs"] = {
            "after_delegation": delegated,
            "before_release": before_release,
            "after_release": after_release,
        }
        report["checks"] = {
            "spoken_delegation": checked(
                exactly_one_worker=len(requests(deleg, "worker_request")) == 1,
                correct_goal=any(
                    "winter" in t.lower() for t in requests(deleg, "worker_request")
                ),
                no_foreground=not requests(deleg, "foreground_request"),
                durable_running=len(delegated) == 1
                and delegated[0]["status"] == "running",
                spoken_receipt=any(
                    matches(r, "transport_utterance_completed") for r in deleg
                ),
            ),
            "foreground_during_job": checked(
                routed_rain=len(requests(fg, "foreground_request")) == 1
                and any(
                    "rain" in t.lower() for t in requests(fg, "foreground_request")
                ),
                received_pcm=bool(rain_pcm),
                worker_active=len(delegated) == 1
                and delegated[0]["status"] == "running",
                no_new_worker=not requests(fg, "worker_request"),
            ),
            "overlapped_backchannel": backchannel_evidence(
                with_prior_pcm(ack, "acknowledge"), onsets["acknowledge"], old
            ),
            "spoken_redirection": checked(
                overlapped=overlap(
                    with_prior_pcm(corr, "correct"), onsets["correct"], old
                ),
                routed_snow=len(requests(corr, "foreground_request")) == 1
                and any(
                    "snow" in t.lower() for t in requests(corr, "foreground_request")
                ),
                old_stopped=old is not None
                and old_cancel is not None
                and not any(
                    matches(r, "pcm", context=old) and r["mono_ns"] > old_cancel
                    for r in corr
                ),
                new_reply_receipt=any(
                    matches(r, "transport_utterance_completed")
                    and r["utterance"] in new_pcm
                    and r["utterance"] == reply_context(corr)
                    for r in corr
                ),
                no_new_worker=not requests(corr, "worker_request"),
            ),
            "job_lifetime": checked(
                unchanged_and_running=len(delegated) == 1
                and delegated == before_release,
                completed_after_release=len(after_release) == len(delegated) == 1
                and after_release[0]["id"] == delegated[0]["id"]
                and after_release[0]["revision"] == delegated[0]["revision"]
                and after_release[0]["status"] == "completed",
            ),
        }
    finally:
        worker.release.set()
        try:
            if control:
                await control()
            if run_task:
                await run_task
        finally:
            await speech.close()
            await runtime.close()
            for context, pcm in (captures.items() if keep_audio else ()):
                save_wave(
                    out / ("output-" + context.replace(":", "-") + ".wav"), pcm, 24000
                )
            report["observed"] = {
                label: {
                    "start_ns": windows[label][0],
                    "end_ns": windows[label][1],
                    "partial_asr": requests(segment(label), "asr_partial"),
                    "final_asr": requests(segment(label), "asr_final"),
                    "foreground_requests": requests(
                        segment(label), "foreground_request"
                    ),
                    "worker_requests": requests(segment(label), "worker_request"),
                    "floor_decisions": [
                        r["decision"]
                        for r in segment(label)
                        if matches(r, "floor_decision")
                    ],
                    "completed_utterances": [
                        {"context": r["utterance"], "bytes": r["bytes"]}
                        for r in segment(label)
                        if matches(r, "transport_utterance_completed")
                    ],
                }
                for label in windows
            }
            with (out / "events.jsonl").open("w") as stream:
                for row in events():
                    stream.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--acknowledgment",
        choices=ACKNOWLEDGMENTS,
        default="mm-hmm",
        help="Use yeah for the separate positive control",
    )
    parser.add_argument(
        "--scenario",
        choices=("duplex", "checkpoint"),
        default="duplex",
        help="checkpoint exercises a disfluent delegation and spoken return",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "supplemental digital PCM, software transport receipts",
        "clock": "single process monotonic_ns; 20 ms software sink buffers",
        "ownership": "course bypass",
        "foreground": "fixed answer fixture",
        "worker": "gated fixture, real durable supervisor",
        "scenario": args.scenario,
        "memory": "durable job checkpoint; personal profile memory disabled",
        "output_tts": "warmed by synthesis of the input stimuli",
        "acknowledgment": args.acknowledgment if args.scenario == "duplex" else None,
        "vad": "Silero",
        "endpointing": "SmartTurn",
        "checks": {},
    }
    try:
        asyncio.run(evaluate(args.output, report, args.acknowledgment, args.scenario))
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["checks"], indent=2))
    return (
        0
        if report["checks"]
        and all(check["passed"] for check in report["checks"].values())
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
