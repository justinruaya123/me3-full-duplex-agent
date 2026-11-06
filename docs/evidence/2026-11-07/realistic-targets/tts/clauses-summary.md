# Clause partition correction

Only `me3/incremental.py` and `tests/test_incremental_v1.py` changed. The tracked
files were frozen and handed to the root for the full installed-suite snapshot
after focused GREEN. No commit, native inference or HTTP request was performed
for this correction.

The source now inspects incoming characters in order, retaining at most the
240-character clause buffer plus one overflow/lookahead character. A punctuation
mark at a delta boundary waits for real following whitespace or stream EOF.
Known abbreviations and dotted initials are conservative continuations. Normal
confirmed punctuation/whitespace and newline boundaries still emit before the
source completes, and the generator does not pull later source deltas while a
consumer handles an emitted clause.

The finite English abbreviation guard includes titles (`Mr.`, `Mrs.`, `Ms.`,
`Mx.`, `Dr.`, `Prof.`, `Sr.`, `Jr.`, `St.`, `Mt.`), common forms (`vs.`, `etc.`,
`e.g.`, `i.e.`, `approx.`, `dept.`, `No.`, `Fig.`, `Inc.`, `Ltd.`, `Co.`,
`Corp.`, `Ph.D.`, `a.m.`, `p.m.`), abbreviated months and dotted single-letter
initials/acronyms. It is explicitly not a general English sentence tokenizer.
An abbreviation that really ends a sentence conservatively waits for another
confirmed boundary or EOF. No text is added or silently dropped.

Emergency cuts occur at whitespace and do not separate an abbreviation tail
from following text. Contiguous source words, numeric spans and version/date
tokens remain intact. An indivisible over-limit token fails with `BufferError`
before any fragment of that token is emitted.

Evidence:

- Initial RED: 13 focused tests, 201 failing subtest assertions, zero errors.
- Final regression check against unmodified `HEAD` clause function: 14 tests,
  212 failures, zero errors/skips. This check substituted only the historical
  function in process; production files were not reverted.
- Final GREEN: **14/14 incremental tests**, zero failures/skips, 0.025s.
- Related control regression: **18/18 duplex/controller tests**, zero
  failures/skips, 0.031s.
- Changed files compile and `git diff --check` passes.
- Full-suite and commit are owned by the root stage coordinator.

Seven added behavioral tests cover decimal continuation; hand-specified output
under whole text, every two-part split and widths 1..7; pending-delta silence;
early confirmed emission/backpressure; bounded long-text word order; numeric,
date, version and ordinary-word spans actually straddling character 240; and
explicit over-limit failure with zero partial-token emission.

## Proposed comma/colon experiment, not implemented

The native evidence suggests earlier full clauses can help where complete
segments exceed about 100 phonemes. A conservative first development candidate
would allow a comma/colon after **at least six whitespace-delimited lexical
words and 40 non-leading characters**, with actual following whitespace. This
is a proposed experiment minimum, not an acceptance threshold or proof of
semantic substance. Preserve the 240-character emergency limit.

Before enabling it, use independent literal fixtures and arbitrary source
partitions to require all of the following:

1. Complete source words/numbers occur once and in order across all output.
2. Decimal/grouped numbers, dates, times, versions, abbreviations and initials
   remain indivisible; numeric-adjacent commas/colons are ineligible.
3. Colons inside URLs, timestamps, ratios and code do not trigger emission.
4. Short acknowledgements and preambles below the minimum remain buffered.
5. An eligible boundary emits before EOF with no source read-ahead, while
   cancellation closes the stream and old epochs remain fenced by the caller.
6. Native saved speech includes the full source, no artificial filler, and
   acceptable pauses/prosody; measure first substantive audio and total audio.

Word/character minima cannot prove a complete thought. Long names, appositives,
lists, quotations and dependent clauses can satisfy them while being unnatural
speech boundaries. Splitting can alter phonemization context, prosody, total
synthesis work and the number of HTTP/receipt boundaries. Character count also
underestimates expanded numeric speech, as the current native profile shows.
Freeze the rule on generated development texts and reject it if coverage,
prosody, cancellation/backpressure or total response behavior regresses. Do not
choose the minimum from held-out benchmark labels.
