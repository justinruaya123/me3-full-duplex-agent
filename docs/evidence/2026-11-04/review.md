# Independent review and fix evidence

One independent read-only reviewer examined the whole change from `642cc73`
through stage 6 before the fix pass. No critical finding was reported. The
reviewer reproduced running-focus silence, preview reconnect HTTP 404, and
unreported provider failure. The five material findings were:

| Finding | Regression/fix |
| --- | --- |
| Inactivity expiry did not gate notices | `test_idle_expiry_revokes_result_delivery_without_new_speech`; delivery-time ownership callback and monitor expiry |
| Focus on running jobs suppressed conversation | `test_focusing_running_job_preserves_unrelated_conversation`; only guard a completed result actually used as context |
| Old preview listener retained closed-session authority | `test_preview_reopens_after_same_owner_reconnects`; session-bound listeners retired on end/rebound on launch |
| Foreground/worker failures were silent | `test_foreground_and_worker_failures_are_reported_without_success`, `test_stale_provider_failure_does_not_replace_newer_turn`; explicit epoch-fenced error/owner-filtered notices |
| Repeated committed requests created duplicate work | `test_distinct_turn_ids_reuse_identical_active_job`; same-owner identical active-request reuse |

The two smaller review findings were treated as important lifecycle/resource
issues and fixed in the same pass: `test_mute_during_enrollment_erases_late_reference`
and `test_partial_upload_reserves_single_role_capacity` reproduce enrollment
completion after mute and admission before upload parsing.

Further self-review regressions protect cross-session playback tokens, inert
model-returned command text, failed-probe readiness, bounded ASR snapshots,
completed-job queue capacity, duplicate active revisions and explicit queue-full
reporting. A real stalled native MLX probe motivated
`test_cancelled_native_inference_remains_busy_until_thread_finishes`: cancelling
the async waiter cannot release native capacity until the actual thread finishes.

Each changed behavior has RED evidence in stage*-red.txt/review-red.txt and a
fresh final complete-suite receipt. No post-fix second reviewer was dispatched;
fixes were verified with regression tests and the full suite. Physical speech,
provider entitlement and target-hardware qualification were not inferred from
this review.
