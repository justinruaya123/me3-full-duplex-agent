# Foreground V2: clarification before boilerplate

Prepared only. No provider/TTS/native call or production edit is authorized by
preparation. The parent owns the next network and native TTS slots.

## V1 failed gate retained

V1 run `run-20261106T213440560521Z` completed 24/24 real Qwen calls. The parent
reviewed all full outputs and found numeric/fact preservation in the candidate,
but `ambiguous_referents` returned:

> I cannot perform physical actions. I am an AI.

It asked no clarification question. The baseline control also omitted a
clarification. The baseline asked a later generic clarification but did not
resolve the required object/destination information. Preserve every failure.
V1 **must not be promoted**: shorter sentences do not repair missing useful
content. Its candidate first-clause median of 34 characters versus baseline
40.5 and control 43.5 is descriptive evidence only.

`v1-failed-gate.json` records that decision, the failing answers and hashes of
the untouched V1 cases, prompts, runner and result files. No old guard, case,
result or score is changed.

## V2 change and frozen holdouts

V2 keeps the short complete sentence / useful content / numbers / qualifications
rules and adds:

> Ask one specific clarifying question when context is missing. Do not guess
> missing facts. Avoid boilerplate and 'as an AI' statements. State a concrete
> capability limit only when relevant.

Put a needed clarification first. Keep the 12-word instruction an aim, with
additional complete short sentences for necessary details. Unsupported actions
still require an honest concrete boundary, such as inability to send an email;
they never authorize a claim of completion.

The eight original case objects and literal guards are copied unchanged into
the V2 cases file. Two new questions in `holdouts.json` were fixed before V2
provider calls to screen whether the general rule transfers:

- “Should I use the first one or the second one?” The alternatives/context are
  unknown. Ask a specific missing-comparison question without choosing an option.
- “I scored 80%. Can I tell the class I passed?” The pass threshold/rules are
  unknown. Ask about that criterion and avoid asserting pass/fail from 80% alone.

The guards accept broad properties rather than a canned first answer. They
require an actual question and relevant missing information. Repeating 80% is
optional when asking for the missing criterion; changing its value is not.
Option-selection/pass-claim regexes are review flags, not a semantic judge.
These are two development holdouts relative to V1 feedback, not a large or
independent population qualification. Do not retune against their future
outputs and continue calling them unseen holdouts.

## Execution and quality criteria

The V2 runner is a separate copy so V1 remains reproducible. It uses the same
real `ForegroundBackend`, exact configured Qwen selection, disabled thinking,
512-token cap, exact model checks, no tools and unchanged serial request bounds.
It captures the actual current controller baseline prompt; conversation JSON is
identical between arms. Default: 20 calls (10 cases x 2 arms); optional identical
baseline control makes 30. Repeats 1–5, 30 s/request and 240 s/run defaults remain.
The existing auth/rate-limit/three-error stop and 600 s maximum run bound remain.

An optional `--http-trace` uses HTTPX's public request `extensions` trace
callback. Each event stores only its library event name and relative
`time.monotonic()` time, with the same zero as first-text/first-clause timing
before client creation. It never reads or retains callback info, URLs, hosts,
headers or auth. It records at most 256 events per request and flags overflow.
HTTPX/httpcore versions are included because available event names can vary.
This is private pilot instrumentation; the production backend is unchanged.

TCP/TLS start/complete pairs can show connection setup. Request-send to response
headers/first text can show where client-observed waiting occurs. Those gaps
still include network, proxy, provider queue and server work; they cannot by
themselves isolate model inference. Headers may arrive before first text. Do not
subtract any phase to turn it into a claimed acoustic result. The trace is
prepared from public HTTPX extension documentation and inspected installed
async callback behavior, but has not yet been exercised on a real request.

API sources: [HTTPX extensions](https://www.python-httpx.org/advanced/extensions/)
and [HTTPX trace wiring](https://github.com/encode/httpx/blob/master/httpx/_main.py).

Keep full answers and actual first clauses, all V1 measurements/guards, safe
model/finish metadata and explicit failures. V2 additionally records AI boilerplate,
generic physical disclaimers, question count and exactly-one-question screens
for the three missing-context cases.

Do not promote unless manual review of every full answer preserves all facts,
numbers and necessary qualifications, asks a specific clarification for all
missing-context cases, and avoids boilerplate/filler/false action claims. A
literal match or short sentence alone is insufficient. Retain failed baseline,
control and candidate answers. Provider-complete does not mean quality passed.

Only after the quality gate passes should the parent run independent native
Kokoro checks on the actual unchanged first project clauses. Text readiness and
character counts do not establish first audio latency; no truncation or filler
may be used to improve that measurement. Baseline-control variation and the
small number of cases limit causal and p95 claims.

Safe preparation:

```sh
.venv313/bin/python .local/verification/targets/foreground/v2/pilot.py prepare
```

After the parent explicitly grants the next network slot:

```sh
.venv313/bin/python .local/verification/targets/foreground/v2/pilot.py run \
  --execute --repeats 1 --baseline-control --http-trace
```

No provider call has run during V2 preparation. Production is unchanged.
