# Conversation-return review

Reviewed the current `hermes/conversation-return-v1` work against base `2dc3554`, the approved local plan, the November 4 specification and duplex invariants. Production and tests were not edited. The following two findings were reproduced with the installed `.venv313/bin/python`, real local runtime/controller state and fixture inference. The existing full suite was not rerun.

## Scoped re-review verdict: both findings resolved

Inspected the subsequent fixes and regression tests for the two findings only. No unresolved finding remains in this scope. This verdict is a code-review conclusion; no additional tests or full suite were run by the reviewer during re-review. Final green-suite verification remains with the implementing agent.

- **Preference acknowledgement: resolved.** The site/defer/notify branches now rebind the closure's `epoch` immediately after the synchronous policy mutation, so a preference change's own invalidation cannot make the newly scheduled acknowledgement stale. There is no intervening `await`. `OwnedJobs.set_return_policy()` still authorizes and checks revision/value before returning early on an unchanged policy, preventing unnecessary invalidation on retries. The new focused-job regression exercises changed-policy `/notify` followed by `/defer` and expects one acknowledgement each. The preserved `review-return-red.log` confirms this regression failed before the fix.
- **Number-dictation cue: resolved.** The finite gate now rejects `digit`/`digits`, `number`/`numbers` and spelled-out English number words, including every number in the reproduced fragment. The controller-level sensitive-fragment regression includes the exact reproduction and expects `hold`, no cue speech and no authorization. The preserved `review-listening-red.log` confirms that fragment previously returned `listening` and emitted `Mm-hm.`. This remains a finite conservative English gate, not a claim of general dictation classification.

The original findings and reproductions below are retained as the historical review record.

## P2 — Keep preference-command acknowledgement on the current epoch

Location: `me3/duplex.py:497-508` (also `me3/jobs.py:104-105`).

`set_return_policy()` invokes the runtime's `changed` callback. If the affected job is in focus, `invalidate_job()` increments the controller epoch synchronously. `_job_command()` subsequently schedules its acknowledgement with the epoch captured before this invalidation, so `_deliver()` discards it. This makes `/notify` and `/defer` silently save their preference without acknowledging the owner's request. Repeating an already-saved policy has the same effect because the setter always invalidates output. The new website submission path can encounter the same problem when submission deduplicates to an existing focused website job.

Reproduction:

1. Open an `AgentRuntime` session as `alice`, submit a draft and await completion.
2. Set `controller.focus` to that job (the public `/focus ID` command reaches the same state).
3. Call `await controller.accept('/notify ' + job_id + ' after_topic')` and settle controller tasks.
4. The result is `notify` and the persisted policy is `after_topic`, but the `speak` callback is never invoked. Observed controller epoch: `0 -> 2` (one normal accept interruption plus one preference invalidation).

Ensure the command's newly authorized acknowledgement uses the current post-mutation epoch while retaining cancellation/fencing of obsolete job audio. Add focused-job coverage for both preference commands, including an unchanged-policy retry.

## P2 — Suppress cues for recognized spoken-number dictation

Location: `me3/conversation.py:36-40`.

The cue gate recognizes numeric characters and the single word `number`, but lets clear number dictation through when the recognizer spells out digits. For example, `The digits are one two three four, um.` passes `listening_safe()` and an ended, owner-addressed, uncommitted transcript emits `Mm-hm.`. This is an explicit suppression case in the November 4 interaction requirements, not an unknown general semantic case. The existing test only covers an Arabic digit (`42`) alongside the exact word `number` and does not detect it.

Reproduction with an otherwise idle authorized runtime/controller:

```python
text = 'The digits are one two three four, um.'
event = TranscriptRevision('s', 't', 1, text, 0, 1,
                           capture_ended=True)
controller.user_started()
controller.user_stopped()
outcome = await controller.transcript(event, addressed=True)
```

Observed: `listening_safe(text) == True`, `outcome == 'listening'`, and `speak('Mm-hm.')` runs. The transcript remains provisional and the cue is correctly absent from history; the defect is cue eligibility during number dictation. Extend the conservative finite rejection gate to recognize spoken numeric sequences/dictation markers and test this through the controller, preserving the default of holding uncertain sensitive fragments.
