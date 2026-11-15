# Lightweight personalized runtime memory

ME3 has an **opt-in, local, dependency-free text memory** for the voice/text
agent. This is separate from the Pi coding assistant's `pi-memory` extension.
It needs no vector database, embeddings, third LLM, or extra service.

## Enable and use

In the ignored operator `.env`:

```sh
ME3_MEMORY_ENABLED=1
ME3_STATE_DIR=.local/runtime
```

Start the existing entrypoint with `./scripts/me3.sh console` or
`./scripts/me3.sh voice`. Keep the same state directory across launches.
Memory is created at `<ME3_STATE_DIR>/memory.sqlite3`, with mode 0600, alongside
(not inside) the existing job database. The default state directory is ignored
by Git. An alternative state directory must be kept private and out of Git.
The feature is off by default in other checkouts; invalid enable values fail
explicitly. No old coding-agent sessions or conversations are imported.

Use the **same trusted owner label** when reconnecting. The console defaults to
`local-operator`. In voice mode, the local operator's `/enroll OWNER` binds that
label after wake and independent verification. A spoken name is not identity,
and a returning speaker still needs fresh session ownership. Using different
labels intentionally creates separate memories. These labels are not strong
sensitive-action authentication; the host operator can access the database.

### Conversation and personalization

With memory enabled, accepted, committed user turns are retained automatically.
Only assistant clauses with confirmed software playback receipts are retained;
generated text, cancelled/unknown playback, partial ASR, bystanders, wake and
enrollment audio are not conversation memory. A receipt is not acoustic proof.
No audio or speaker reference is saved by this feature.

Long-term personal facts and project descriptions are **explicit**, not inferred
by a background model. For example, say:

```text
Remember that I prefer concise answers
Remember that I am working on a painting portfolio
What do you remember about me?
What did we discuss about the portfolio?
Recall portfolio
```

The first two create notes with announced `fact-...` keys. Normal conversational
questions receive bounded retrieved context through the selected foreground
model. `recall QUERY` is a provider-independent, deterministic history listing;
it returns historical data, not a claim of current task completion.

For named notes, corrections and projects, use the trusted console syntax:

```text
/remember preference = Keep explanations concise
/project portfolio = A painting portfolio with a purple palette
/project portfolio = The palette is now green
/memory
/recall portfolio
/forget preference
```

Replacing a key updates the existing note, rather than adding another copy.
The spoken project form is `remember project NAME: DETAILS` (the recognized
text must contain the colon). You can also say `forget memory KEY`.
Memory commands and their displayed contents are not themselves archived, so
forgetting a note does not immediately rediscover its original save command.

### Tasks during the same voice session

Keep talking while using existing explicit job commands, for example:

```text
/project portfolio = My painting portfolio uses a green palette
/site build my portfolio website
What did we decide about my portfolio?
/jobs
/status JOB_ID
/result JOB_ID
/revise JOB_ID change the portfolio layout
```

The foreground receives relevant saved text plus up to eight recent **current,
owner-filtered** job IDs, revisions, requests and statuses. Job truth still comes
from the durable job store, never a remembered claim. Retrieval does not switch
focus, deliver a notice, authorize work or replay a task.

At worker inference time, up to eight lexically relevant saved notes can be
included in a bounded, labelled data block. Workers do **not** get the whole
conversation archive, direct database access, or memory-writing tools. The
website JSON/build/verification path, revision checks and permission boundaries
remain unchanged. No autonomous task routing, calendar integration, public
deployment, or unrestricted personalized actions are added.

## Privacy and forgetting

- `/memory off` or `turn memory off`: pause this owner's retention and retrieval;
  saved data remains. Ordinary in-session conversation still works.
- `/memory on` or `turn memory on`: resume. Does not restore deleted records.
- `/forget KEY` or `forget memory KEY`: delete a note and archived messages
  containing its literal value, case-insensitively.
- `/memory clear` or `forget all memories`: delete this owner's notes,
  conversation messages and session metadata, then pause memory. Other owners
  are unaffected. Use `/memory on` to start remembering again.
- Replacing/forgetting notes or changing memory settings clears rolling context
  and fences in-flight foreground output in that owner's memory-enabled sessions.
  It does not cancel background jobs or interrupt opted-out/benchmark sessions.

**Deletion limits:** literal matching cannot find every paraphrase or derived
fact. Use `/memory clear` for the whole conversation archive. Job requests,
artifacts, worker harness sessions, operator backups and data already sent to
an inference provider are separate records and are not erased by these commands.
Existing worker inference is not recalled or cancelled by forgetting. SQLite
secure deletion is enabled, but this is not a forensic-erasure guarantee.

Do not store passwords, tokens or other secrets. Local storage is not encrypted.
Retrieved text is sent to your already-configured inference provider as context;
"local memory" describes storage/orchestration, not local-only LLM inference.
Nothing is sent to a new memory provider. Disabling `ME3_MEMORY_ENABLED` stops
using memory but does not delete its database.

## Bounds and evidence

Per owner, the default retention is **64 notes, 32 sessions and 256 messages**.
Each note has a key of at most 64 and a value of at most 1,000 characters.
Archived messages keep at most 4,000 characters with an explicit truncation
flag. Old conversation/session records are evicted; the note limit requires
explicit deletion rather than silently losing saved personal facts.

Retrieval uses simple keyword overlap and recency, not semantic understanding.
Foreground memory context is capped at 7,500 JSON characters; worker note
context at 2,500. It is not an exhaustive transcript or perfect recall. There
is no automatic summary or inferred personality profile. Existing transcript
revision, queue and session-renewal limits are preserved; persistent memory
survives renewal without requiring a single unbounded model context.

Course-profile sessions explicitly opt out, even in a memory-enabled runtime.
The regression suite checks restart recall, owner isolation, accepted-only text,
playback uncertainty, corrections/deletion, long-session retrieval, independent
jobs, personalized static builds, opted-out sessions and storage failure paths.
These are fixture-inference/control tests plus local SQLite/static-build checks,
not live voice, provider, acoustic-latency or target-hardware qualification.
See [DUPLEX_STATUS](DUPLEX_STATUS.md) for exact verification counts.
