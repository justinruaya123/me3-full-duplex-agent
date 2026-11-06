# V2 rejected — no production prompt promotion

This is a private real-provider development pilot, not a ME3 benchmark or an
acceptance result. Canonical ME3 benchmark evidence remains separate.

Run `run-20261106T214446779189Z` completed **30/30** serial requests: ten cases
each for baseline, identical-prompt baseline control, and V2 candidate, using
the exact configured `Qwen/Qwen3.8-27B`. All provider requests completed, but the
candidate failed the parent's full-answer quality review.

| Development screen | Baseline | Baseline control | V2 candidate |
| --- | --- | --- | --- |
| Protocol-complete calls | 10/10 | 10/10 | 10/10 |
| Full-answer literal fact guards | 8/10 | 8/10 | 9/10 |
| First-sentence usefulness guard | 7/10 | 6/10 | 6/10 |
| Median first-sentence whitespace words | 8.5 | 6.5 | 6 |
| Median first project-clause characters | 45 | 37 | 33.5 |
| Exactly one question in three missing-context cases | 1/3 | 1/3 | 3/3 |

These lexical screens do not establish semantic correctness. In particular,
asking one question did not ensure that it addressed the missing information.

The boiling answer stated the correct 100 C figure and mentioned pressure,
passing every literal guard, but included “Lower pressure weakens molecular
cohesion.” The parent rejected that causal explanation. A keyword match cannot
validate a scientific mechanism, and splitting an explanation into short
sentences cannot repair an incorrect claim.

For `ambiguous_referents`, the candidate answered “No, I cannot move physical
items.” before asking which item to move. It assumed a physical interpretation
without context, led with a capability assertion, and omitted the missing
destination. The original destination guard correctly remained false. The
broader first-sentence usefulness screen also remained false.

The two new development holdouts and all original guard definitions remain
unchanged. The unspecified-options answer asked a relevant clarifying question.
The passing-threshold answer acknowledged uncertainty but its first sentence
did not pass the frozen useful-first guard. None of this overrides the failed
boiling and original ambiguity cases. No guard was retuned after observing the
outputs, and every baseline/control/candidate failure remains in the records.

The smaller candidate first-clause median is descriptive only. Baseline-control
variation, small case counts and failed quality prohibit treating it as a safe
latency improvement. V2 has not been promoted into the production prompt; no V3
is being prepared. No native TTS measurement of V2 was run by this agent.

`manual-gate-failed.json` records the rejection and exact failing outputs.
`review-summary.json` contains raw-record counts, first-clause screens and
non-sensitive client trace-gap diagnostics. Original prompts, cases, guards,
HTTP traces and full provider answers stay untouched in the run directory.
Transport timings are provider-development diagnostics, not acoustic or ME3
benchmark results, and cannot isolate model inference from network/proxy/queue
waiting.
