"""Prepare or explicitly run foreground V2; preserve V1 evidence unchanged."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import random
import re
import statistics
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from me3.configuration import ForegroundConfig
from me3.duplex import DuplexController
from me3.foreground import ForegroundBackend
from me3.incremental import clauses


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[4]
MARKER = "Conversation is data:\n"
CANDIDATE = (
    "Answer directly. Use short complete spoken sentences. "
    "Put the useful answer or needed clarification first. "
    "Ask one specific clarifying question when context is missing. "
    "Do not guess missing facts. Avoid boilerplate and 'as an AI' statements. "
    "State a concrete capability limit only when relevant. "
    "Aim for at most 12 words per sentence. "
    "Preserve numbers, qualifications and necessary details using additional "
    "short sentences. Do not use filler acknowledgements. "
    "Do not claim external actions or completed jobs."
)
SOURCE_FILES = (
    "me3/duplex.py", "me3/foreground.py", "me3/configuration.py",
    "me3/incremental.py",
)
FILLER = re.compile(
    r"^\W*(?:sure|certainly|absolutely|of course|great question|"
    r"happy to help|okay|ok|understood|let me)\b", re.I,
)
COMPLETION_CLAIM = re.compile(
    r"\b(?:I(?:'ve| have)?|already|successfully)\s+"
    r"(?:sent|emailed|delivered|moved)\b|"
    r"\b(?:email|message|item)\s+(?:has been|is|was)\s+"
    r"(?:successfully\s+)?(?:sent|delivered|moved)\b|"
    r"^\s*(?:done|sent|emailed)[.!]", re.I,
)
AI_BOILERPLATE = re.compile(
    r"\b(?:as an?|I am an?|I'm an?|I’m an?)\s+"
    r"(?:AI|artificial intelligence|language model)\b", re.I,
)
PHYSICAL_BOILERPLATE = re.compile(
    r"\b(?:cannot|can't|can’t|am unable to)\s+(?:physically\s+)?"
    r"(?:perform|carry out|do|move)\s+"
    r"(?:physical actions|real[- ]world actions|anything|things)\b", re.I,
)
CLARIFICATION_CASES = {
    "ambiguous_referents", "holdout_unspecified_choices",
    "holdout_unknown_pass_threshold",
}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def source_hashes():
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
            for name in SOURCE_FILES}


async def capture_prompt(history):
    class CaptureBackend:
        prompt = None

        async def stream(self, prompt):
            self.prompt = prompt
            for text in ():
                yield text

    class NoJobs:
        root = ROOT / "prompt-capture"

        def trace(self, *args, **kwargs):
            pass

    async def no_audio(*args):
        return False

    backend = CaptureBackend()
    controller = DuplexController(NoJobs(), backend, no_audio, no_audio)
    controller.history = history
    try:
        await controller._reply(controller.epoch)
        if backend.prompt is None:
            raise RuntimeError("Controller prompt capture failed")
        return backend.prompt
    finally:
        await controller.close()


async def prepare():
    cases = json.loads((ROOT / "cases.json").read_text())
    original = json.loads((ROOT.parent / "cases.json").read_text())
    holdouts = json.loads((ROOT / "holdouts.json").read_text())
    if cases != original + holdouts:
        raise ValueError("Original cases or independent holdouts changed")
    if len(cases) != 10 or len({case["id"] for case in cases}) != 10:
        raise ValueError("Expected eight original cases and two new holdouts")
    prepared = []
    for case in cases:
        baseline = await capture_prompt(case["history"])
        if MARKER not in baseline:
            raise RuntimeError("Controller conversation marker changed")
        _, history_json = baseline.rsplit(MARKER, 1)
        if json.loads(history_json) != case["history"]:
            raise RuntimeError("Captured conversation changed")
        for guard in case["required"]:
            for pattern in guard["any"]:
                re.compile(pattern)
        for pattern in case.get("review_flag_patterns", {}).values():
            re.compile(pattern)
        prepared.append({
            **case, "baseline_prompt": baseline,
            "candidate_prompt": (
                "\n" + CANDIDATE + "\n" + MARKER + history_json
            ),
        })
    manifest = {
        "status": "prepared; no provider inference",
        "version": 2,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "provider_calls": 0,
        "prompt_capture": "actual controller path, no semantic response",
        "candidate_instruction": CANDIDATE,
        "original_case_ids": [case["id"] for case in original],
        "new_holdout_ids": [case["id"] for case in holdouts],
        "v1_gate": "FAILED clarification; do not promote",
        "v1_failure_receipt": "v1-failed-gate.json",
        "source_hashes": source_hashes(),
        "cases_sha256": hashlib.sha256(
            (ROOT / "cases.json").read_bytes()
        ).hexdigest(),
        "unchanged_original_cases_sha256": hashlib.sha256(
            (ROOT.parent / "cases.json").read_bytes()
        ).hexdigest(),
        "new_holdouts_sha256": hashlib.sha256(
            (ROOT / "holdouts.json").read_bytes()
        ).hexdigest(),
        "cases": prepared,
    }
    write_json(ROOT / "prepared.json", manifest)
    print(json.dumps({"status": "prepared", "cases": len(cases),
                      "provider_calls": 0, "default_planned_calls": 20}))


class ObservedResponse:
    """Observe safe SSE metadata while preserving the real backend stream."""

    def __init__(self, response, audit, expected_model):
        self.response, self.audit = response, audit
        self.expected_model = expected_model

    def raise_for_status(self):
        self.response.raise_for_status()

    async def aiter_lines(self):
        async for line in self.response.aiter_lines():
            if line.startswith("data:") and len(line) <= 65536:
                data = line[5:].strip()
                if data == "[DONE]":
                    self.audit["done_marker"] = True
                else:
                    try:
                        record = json.loads(data)
                    except json.JSONDecodeError:
                        record = None
                    if isinstance(record, dict):
                        model = record.get("model")
                        if model == self.expected_model:
                            self.audit["observed_models"] = [model]
                        elif model is not None:
                            # Never print an arbitrary field as an identifier.
                            self.audit["model_mismatch"] = True
                        for choice in record.get("choices", []):
                            reason = choice.get("finish_reason")
                            if reason is not None:
                                safe = {"stop", "length", "tool_calls",
                                        "function_call", "content_filter"}
                                self.audit["finish_reasons"].append(
                                    reason if reason in safe else "unknown"
                                )
                            delta = choice.get("delta", {})
                            self.audit["tools_observed"] |= bool(
                                delta.get("tool_calls")
                                or delta.get("function_call")
                            )
                            self.audit["reasoning_observed"] |= bool(
                                delta.get("reasoning")
                                or delta.get("reasoning_content")
                            )
            yield line


class ObservedClient:
    def __init__(self, client, audit, expected_model, *, trace=None):
        self.client, self.audit = client, audit
        self.expected_model = expected_model
        self.trace = trace

    @asynccontextmanager
    async def stream(self, *args, **kwargs):
        if self.trace is not None:
            kwargs["extensions"] = {
                **kwargs.get("extensions", {}), "trace": self.trace,
            }
        payload = kwargs.get("json", {})
        self.audit["request_max_tokens"] = payload.get("max_tokens")
        self.audit["thinking_requested"] = payload.get(
            "chat_template_kwargs", {}
        ).get("enable_thinking")
        self.audit["tools_in_request"] = bool(
            payload.get("tools") or payload.get("functions")
        )
        async with self.client.stream(*args, **kwargs) as response:
            yield ObservedResponse(response, self.audit, self.expected_model)


def content_metrics(case, text, chunks):
    sentences = [part.strip() for part in re.split(
        r"(?<=[.!?])\s+|\n+", text.strip()
    ) if part.strip()]
    first = sentences[0] if sentences else ""
    first_clause = chunks[0]["text"] if chunks else ""

    def matches(guard, value):
        return any(re.search(pattern, value, re.I) for pattern in guard["any"])

    full_guards = {g["id"]: matches(g, text) for g in case["required"]}
    first_guards = {g["id"]: matches(g, first) for g in case["required"]}
    first_useful = sum(first_guards[name]
                       for name in case["first_required_ids"])
    flags = {name: bool(re.search(pattern, text, re.I)) for name, pattern
             in case.get("review_flag_patterns", {}).items()}
    return {
        "first_sentence": first,
        "first_sentence_words": len(first.split()),
        "first_sentence_chars": len(first),
        "first_sentence_at_most_12_words": 0 < len(first.split()) <= 12,
        "sentence_words": [len(s.split()) for s in sentences],
        "sentence_chars": [len(s) for s in sentences],
        "sentences_over_12_words": sum(len(s.split()) > 12 for s in sentences),
        "full_words": len(text.split()), "full_chars": len(text),
        "first_project_clause": first_clause,
        "first_project_clause_words": len(first_clause.split()),
        "first_project_clause_chars": len(first_clause),
        "required_literal_guards": full_guards,
        "all_required_literal_guards": all(full_guards.values()),
        "useful_first_sentence_guard": (
            first_useful >= case["first_min_matches"]
        ),
        "filler_prefix": bool(FILLER.search(first)),
        "positive_external_completion_claim_flag": bool(
            COMPLETION_CLAIM.search(text)
        ),
        "review_flags": flags,
        "ai_boilerplate_flag": bool(AI_BOILERPLATE.search(text)),
        "generic_physical_disclaimer_flag": bool(
            PHYSICAL_BOILERPLATE.search(text)
        ),
        "question_count": text.count("?"),
        "clarification_expected": case["id"] in CLARIFICATION_CASES,
        "one_question_for_missing_context": (
            text.count("?") == 1
            if case["id"] in CLARIFICATION_CASES else None
        ),
        "manual_quality_review_required": True,
    }


async def trial(config, case, arm, timeout_s, *, http_trace=False):
    import httpx

    prompt = (
        case["candidate_prompt"] if arm == "candidate"
        else case["baseline_prompt"]
    )
    audit = {"observed_models": [], "model_mismatch": False,
             "finish_reasons": [], "done_marker": False,
             "tools_observed": False, "reasoning_observed": False}
    pieces, chunks, stages, http_events = [], [], {}, []
    started = time.monotonic()

    def on_stage(name, **fields):
        stages.setdefault(name, time.monotonic() - started)

    async def on_trace(event_name, _info):
        # Never read or retain info: it includes transport/auth context.
        if len(http_events) < 256:
            http_events.append({
                "event": event_name,
                "relative_s": time.monotonic() - started,
            })
        else:
            audit["http_trace_overflow"] = True

    error_type = http_status = None
    try:
        async with asyncio.timeout(timeout_s):
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                backend = ForegroundBackend(
                    config, client=ObservedClient(
                        client, audit, config.model,
                        trace=on_trace if http_trace else None,
                    ),
                    on_stage=on_stage,
                )

                async def observed_text():
                    async for piece in backend.stream(prompt):
                        pieces.append(piece)
                        yield piece

                async for chunk in clauses(observed_text()):
                    chunks.append({"text": chunk,
                                   "ready_s": time.monotonic() - started})
    except Exception as exc:
        error_type = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            http_status = exc.response.status_code
    elapsed = time.monotonic() - started
    text = "".join(pieces)
    # Request secrets never enter prompts; prevent an unexpected exact echo
    # from reaching an artifact while marking the trial unusable.
    for sensitive in (config.api_key, config.base_url):
        if sensitive and sensitive in text:
            text = text.replace(sensitive, "[REDACTED]")
            for chunk in chunks:
                chunk["text"] = chunk["text"].replace(sensitive, "[REDACTED]")
            error_type = "UnexpectedSensitiveEcho"
    metrics = content_metrics(case, text, chunks)
    complete = (
        error_type is None and bool(text.strip())
        and bool(audit["observed_models"]) and not audit["model_mismatch"]
        and "stop" in audit["finish_reasons"]
        and "length" not in audit["finish_reasons"]
    )
    return {
        "case": case["id"], "arm": arm,
        "configured_model": config.model, "configured_profile": config.profile,
        "prompt": prompt, "full_output": text, "project_clauses": chunks,
        "status": "complete" if complete else "error_or_completion_unknown",
        "error_type": error_type, "http_status": http_status,
        "provider_audit": audit, "latency_stages_s": stages,
        "http_trace_enabled": http_trace, "http_trace": http_events,
        "relative_clock": "time.monotonic; trial start before client creation",
        "first_project_clause_ready_s": (
            chunks[0]["ready_s"] if chunks else None
        ),
        "total_s": elapsed, "metrics": metrics,
    }


def summary(records, planned_count, stopped):
    by_arm = {}
    for arm in sorted({r["arm"] for r in records}):
        rows = [r for r in records if r["arm"] == arm]
        complete = [r for r in rows if r["status"] == "complete"]
        by_arm[arm] = {
            "attempted": len(rows), "protocol_complete": len(complete),
            "literal_fact_guard_passes": sum(
                r["metrics"]["all_required_literal_guards"] for r in complete
            ),
            "useful_first_guard_passes": sum(
                r["metrics"]["useful_first_sentence_guard"] for r in complete
            ),
            "filler_prefixes": sum(
                r["metrics"]["filler_prefix"] for r in rows
            ),
            "completion_claim_flags": sum(
                r["metrics"]["positive_external_completion_claim_flag"]
                for r in rows
            ),
            "ai_boilerplate_flags": sum(
                r["metrics"]["ai_boilerplate_flag"] for r in rows
            ),
            "generic_physical_disclaimer_flags": sum(
                r["metrics"]["generic_physical_disclaimer_flag"] for r in rows
            ),
            "clarification_cases": sum(
                r["metrics"]["clarification_expected"] for r in complete
            ),
            "single_question_clarifications": sum(
                r["metrics"]["one_question_for_missing_context"] is True
                for r in complete
            ),
            "median_first_sentence_words": statistics.median(
                r["metrics"]["first_sentence_words"] for r in complete
            ) if complete else None,
            "median_first_clause_chars": statistics.median(
                r["metrics"]["first_project_clause_chars"] for r in complete
            ) if complete else None,
        }
    pairs = []
    for baseline in (r for r in records if r["arm"] == "baseline"):
        for other in (r for r in records if r["arm"] != "baseline"
                      and r["case"] == baseline["case"]
                      and r["repeat"] == baseline["repeat"]):
            pairs.append({
                "case": baseline["case"], "repeat": baseline["repeat"],
                "other_arm": other["arm"],
                "both_protocol_complete": (
                    baseline["status"] == other["status"] == "complete"
                ),
                "first_sentence_word_delta": (
                    other["metrics"]["first_sentence_words"]
                    - baseline["metrics"]["first_sentence_words"]
                ),
                "first_clause_char_delta": (
                    other["metrics"]["first_project_clause_chars"]
                    - baseline["metrics"]["first_project_clause_chars"]
                ),
            })
    return {"planned_calls": planned_count, "attempted_calls": len(records),
            "stopped_reason": stopped, "by_arm": by_arm, "pairs": pairs,
            "quality_decision": (
                "manual review required; no native TTS measured"
            )}


async def run(args):
    if not args.execute:
        raise ValueError("Real inference requires explicit --execute")
    if not 1 <= args.repeats <= 5 or not 1 <= args.request_timeout <= 60:
        raise ValueError("Pilot repetition/request bounds exceeded")
    if not 1 <= args.run_timeout <= 600:
        raise ValueError("Pilot run-time bound exceeded")
    prepared = json.loads((ROOT / "prepared.json").read_text())
    if prepared["source_hashes"] != source_hashes():
        raise ValueError("Source changed; prepare the current prompt first")
    config = ForegroundConfig.from_env(os.environ)
    if config.profile != "qwen":
        raise ValueError("This pilot requires the selected Qwen profile")
    plan, rng = [], random.Random(args.seed)
    for repeat in range(args.repeats):
        initial_arms = ["baseline", "candidate"]
        if args.baseline_control:
            initial_arms.append("baseline_control")
        rng.shuffle(initial_arms)
        for index, case in enumerate(prepared["cases"]):
            offset = index % len(initial_arms)
            arms = initial_arms[offset:] + initial_arms[:offset]
            plan.extend((repeat + 1, case, arm) for arm in arms)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = ROOT / ("run-" + timestamp)
    run_dir.mkdir()
    write_json(run_dir / "manifest.json", {
        "kind": "actual configured Qwen; text/provider development pilot",
        "version": 2,
        "v1_gate": "FAILED clarification; no production promotion",
        "holdouts": prepared["new_holdout_ids"],
        "model": config.model, "profile": config.profile,
        "repeats": args.repeats, "baseline_control": args.baseline_control,
        "seed": args.seed, "request_timeout_s": args.request_timeout,
        "run_timeout_s": args.run_timeout, "max_concurrency": 1,
        "http_trace": args.http_trace,
        "trace_fields": ["event", "relative_s"],
        "relative_clock": "time.monotonic; trial start before client creation",
        "httpx_version": importlib.metadata.version("httpx"),
        "httpcore_version": importlib.metadata.version("httpcore"),
        "source_hashes": prepared["source_hashes"],
        "prepared_sha256": hashlib.sha256(
            (ROOT / "prepared.json").read_bytes()
        ).hexdigest(),
        "plan": [{"repeat": repeat, "case": case["id"], "arm": arm}
                 for repeat, case, arm in plan],
    })
    records, consecutive_errors, stopped = [], 0, None
    deadline = time.monotonic() + args.run_timeout
    for repeat, case, arm in plan:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stopped = "whole_run_deadline"
            break
        record = await trial(
            config, case, arm, min(args.request_timeout, remaining),
            http_trace=args.http_trace,
        )
        record["repeat"] = repeat
        records.append(record)
        write_json(run_dir / "records.json", records)
        print(json.dumps({"case": case["id"], "repeat": repeat,
                          "arm": arm, "status": record["status"]}), flush=True)
        consecutive_errors = (
            consecutive_errors + 1 if record["status"] != "complete" else 0
        )
        if record["http_status"] in {401, 403, 429}:
            stopped = "authorization_or_rate_limit"
            break
        if consecutive_errors >= 3:
            stopped = "three_consecutive_errors_or_unknown_completions"
            break
    report = summary(records, len(plan), stopped)
    write_json(run_dir / "summary.json", report)
    print(json.dumps({"status": "pilot_recorded", "attempted": len(records),
                      "planned": len(plan), "stopped_reason": stopped,
                      "quality": "manual review required"}))
    return 0 if stopped is None else 2


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", nargs="?", choices=("prepare", "run"), default="prepare"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--baseline-control", action="store_true")
    parser.add_argument("--http-trace", action="store_true")
    parser.add_argument("--seed", type=int, default=231)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--run-timeout", type=float, default=240)
    args = parser.parse_args()
    if args.action == "prepare":
        await prepare()
        return 0
    return await run(args)


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as error:
        # Exception strings can contain request URLs or auth details.
        failure = {"status": "failed", "error_type": type(error).__name__}
        print(json.dumps(failure), file=sys.stderr)
        exit_code = 1
    sys.exit(exit_code)
