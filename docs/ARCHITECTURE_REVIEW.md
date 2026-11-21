# Architecture review

### D1 · Local BMO voice session

```mermaid
flowchart LR
  mic[Mic] --> asr[Deepgram]
  asr -->|Revisions, settled words and endpoint time| turn[Local turn controller]
  mic --> local[Silero VAD and SmartTurn]
  local --> turn
  local -->|Speech onset pauses playback| tts
  turn -->|Finalized stop clears buffered audio| tts
  turn -->|Committed conversational turn| pi[Project Pi session]
  pi <--> model[OpenRouter]
  pi --> tts[Local BMO Piper and speaker]
  pi --> jobs[Local job supervisor and workers]
```

During a Deepgram turn the controller allows a short gap for a second clause.
If SmartTurn holds the floor, a full second of local quiet can corroborate a
settled sentence. The settled words must cover the last speech and match the
current transcript. A closed sentence has terminal punctuation or a matching
provider endpoint with a non-dangling word ending. Resumed speech restarts the
quiet interval. A late change to the final prevents dispatch on this path.
The loopback routing test uses a fresh draft-only supervisor store. Live mic
authorization, spoken approvals and ordinary course playback retain their
existing gates.

### D2 · Integrated result-return policy

```mermaid
flowchart LR
  saved["Verified result for this owner and revision"] --> choice{"Return preference"}
  choice -->|"Ask first"| explicit["Wait for an explicit request"]
  choice -->|"After topic"| wrap["Wait for committed topic wrap-up"]
  choice -->|"Default"| gate["Quiet floor, owner, revision and cooldown checks"]
  wrap --> gate
  gate --> notice["Brief notice and playback receipt"]
  explicit --> report["Requested report with clause receipts"]
```

The foreground can change a return preference while a job runs. The delivery
controller checks it again before playback. Revising the job starts a new
delivery record. The earlier candidate and benchmark notes below describe the
behavior at their dated revisions.


### D3 · Continue the conversation or steer a job

```mermaid
flowchart LR
  turn[Committed turn] -->|Conversation| thread[Current Pi conversation]
  turn -->|Live Deepgram stop current task| cancel[Local host checks mic and active utterance]
  cancel -->|Current job ID and revision| job[Local supervisor]
  memory[Private cross-chat memory] -->|Fresh chat or explicit recall| thread
  thread -->|Question about active work| status[Local job status]
  thread -->|Requested edit and job revision| job
  thread -->|Uncertain public fact| answer[Brave Answers]
  answer -->|Answers unavailable on plan| web[Brave Web Search]
  thread -->|Request to browse results| web
  web -->|Requested links| ui[IntelligentUI]
  answer --> speech[Short spoken answer]
  web --> speech
```

Pi can use public evidence from the current and preceding two exchanges. Older
chats supply context on request. A normal follow-up uses the conversation already
on the current branch. Edits carry the existing job ID and expected revision.
A new revision retains outstanding notification intent and runs under the same
supervisor. Selected portfolio facts still use the publication review flow.

**R1 · Spoken stop controls (November 21, based on `main@be89121`).** D1 pauses
audio at speech onset. A finalized standalone “stop” clears buffered audio and
invalidates old speech requests, even when the word is too short to confirm
speech over the speaker.
Both stop commands end silently. D3 accepts “stop current task” for cancellation
only from the live Deepgram microphone path after near-end speech, a matching
final and a local commit. The supervisor selects this chat’s running job, or
its first queued job if none has started, and checks its revision. A completed
job keeps its result. Interim words, model output and replay audio have no
cancellation authority. [Verification](DUPLEX_STATUS.md)
