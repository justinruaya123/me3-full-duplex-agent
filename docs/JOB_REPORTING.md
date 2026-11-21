# Durable jobs and spoken reports

The client owns the queue, SQLite state, task checkpoints and output scheduler.
A voice session can end while a job runs. The deployment runtime admits five
unfinished jobs, runs one heavy job at a time, and gives the worker and artifact
verification a combined 600-second deadline after the job starts. An explicit
runtime shutdown or restart marks unfinished jobs interrupted. Only an explicit
owner request can submit a new revision.

## Commands and delivery

| Owner request | Result |
| --- | --- |
| `/task REQUEST` or `/site REQUEST` | Saves the job, owner binding, turn identifier when available, and task checkpoint before acknowledging the queue entry. |
| `/status ID` | Reads the current revision, job state and recorded host progress. The status request can be answered during the unsolicited-notice cooldown. |
| `/focus ID` and `go back` | Save or restore the owner's task checkpoint. Returning reads live job status. It also works after starting a fresh authorized session. |
| `/defer ID` | Holds this revision's brief notice until the owner requests the result. The hold survives a session change. |
| `/result ID` | Reads the saved result in clauses. After roughly 4,000 characters of a long report, the scheduler gives the owner a chance to continue. |
| `continue` | Resumes at the first outstanding clause. When several reports are outstanding, asks for an ID. When only a previously interrupted brief notice is outstanding, repeats that notice. |
| `/revise ID REQUEST` and `/cancel ID` | Act on the named current revision. A revision supersedes its old playback, notice and report cursor. Previously written files can remain on disk. |
| `stop speaking` and `cancel generation` | The first stops playback. The second ends foreground generation and allows an already playing clause to finish. Ambiguous cancellation asks for the intended scope. |

The job state and its host verification events drive status. A worker's
self-description never establishes a check pass. A saved result may be ready
while the owner is speaking, while ASR is unresolved, or during a question or
approval. The scheduler waits through these states, and for 800 ms of quiet,
then coalesces at most three brief notices. A durable per-owner clock spaces
unsolicited offers at least 30 seconds apart. An offer leaves focus untouched.
The trusted console checks for eligible notices while it waits for input.
Attaching voice transfers unsolicited delivery to the voice session and its
ownership gate. The console can still answer explicit text commands. After the
voice session detaches, an open console resumes checking for its own owner.

## Recovery and receipts

Each owner has a task checkpoint. Each job revision has separate receipt state
for its brief notice and its requested report. A report attempt records its
revision, attempt identifier and confirmed character offset. It becomes
uncertain before each clause enters playback. Only a current, authorized
software playback receipt can advance the offset. An interrupted or ambiguous
clause may therefore be repeated. A completed brief notice leaves the full
report available. `continue` reads the saved artifact and never executes a job.

Older databases acquire the additional tables on open. Jobs with a recorded
notice retain it. Earlier jobs acquire a report cursor or checkpoint on the
next explicit operation. Resuming after reconnect requires renewed session
authority.

The SQLite, controller and fixture-transport tests in
[test_job_reporting_v1.py](../tests/test_job_reporting_v1.py) cover queue
admission, rollback, independent cancellation, cooldown, defer/return,
revision fencing, deadline enforcement and interruption/restart. The playback
receipt describes software output. Physical audibility requires the separate
device measurements listed in [deployment status](DUPLEX_STATUS.md).
