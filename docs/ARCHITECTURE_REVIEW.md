# Architecture review

### D1 · Local BMO voice session

```mermaid
flowchart LR
  mic[Mic] --> asr[Deepgram]
  asr -->|Revisions, settled words and endpoint time| turn[Local turn controller]
  mic --> local[Silero VAD and SmartTurn]
  local --> turn
  turn -->|Committed standalone wake| greeting[Cached local greeting]
  turn -->|Committed request| pi[Project Pi session]
  turn -->|Reply still pending after 160 ms| cue[Brief acknowledgment tone]
  pi <--> model[OpenRouter]
  pi --> tts[Local BMO Piper]
  tts --> speaker[Interruptible speaker]
  greeting --> speaker
  cue --> speaker
  pi --> jobs[Local job supervisor and workers]
  pi -->|Operator computer-use session| desktop[Local desktop helper]
  desktop -->|Approved input| app[Selected app]
```

Deepgram proposes segment ends after 250 ms of quiet. A standalone wake can
use a matching segment final after 240 ms of local quiet. A completed question
can use it after 400 ms with SmartTurn confirmation. The segment must cover
the latest voiced frames, including any resumed speech. Other complete turns
retain the grace period for a second clause and can request a provider flush.
While the user speaks, the client opens one standby ASR connection. Only
the active connection receives audio. The standby takes over after the prior
turn has finished or been discarded. We trim
leading quiet from greetings and keep the local voice warm for spoken answers.
The 85 ms acknowledgment uses the same speaker and yields to resumed speech
or an available reply. Mid-clause speech cues require explicit overlap mode.

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
  turn[Committed turn] --> thread[Current Pi conversation]
  memory[Private cross-chat memory] -->|Fresh chat or explicit recall| thread
  profile[Private USER.md] --> thread
  thread -->|Website brief and user-supplied copy| site[Pi website worker]
  thread -->|Website needing timely public information| evidence[Scoped live Brave research]
  evidence -->|Current sources and excerpts| site
  site --> verify[Offline desktop and mobile verification]
  verify --> zip[Local GitHub Pages ZIP]
  thread -->|Question about active work| status[Local job status]
  thread -->|Requested edit and job revision| job[Local supervisor]
  thread -->|Known stable fact or context answers it| speech[Short spoken answer]
  thread -->|Request to do work, including 'Can you ...'| task[Pi handles or delegates the request]
  task -->|Delegated software troubleshooting or code review| debug[Local reviewer: systematic-debugging by default]
  thread -->|Uncertain or changing public fact| search[Live lookup: idle speaker says Searching.]
  search --> answer[Brave Answers]
  answer -->|Answers unavailable on plan| web[Brave Web Search]
  thread -->|Request to browse results| web
  web -->|Requested links| ui[IntelligentUI]
  answer --> summary[Foreground model writes a one- or two-sentence sourced summary]
  web --> summary
  summary --> speech
```

Pi can use public evidence from the current and preceding two exchanges. Older
chats supply context on request. A normal follow-up uses the conversation already
on the current branch. Edits carry the existing job ID and expected revision.
A new revision retains outstanding notification intent and runs under the same
supervisor. Selected portfolio facts still use the publication review flow.
After a lookup, the host voices the model’s lead summary, not a pointer to Pi.
Requested links stay in IntelligentUI. If the search cannot verify the answer,
BMO says so aloud.

### D3 / R10 · Implemented Pi handoff and GitHub Pages publication

On the BMO working tree based on `6b6bf3c`, a completed website has a local ZIP.
R10 adds a public destination for an explicitly selected revision.

```mermaid
flowchart LR
  request[Current request] -->|Work beyond the foreground| worker[Local Pi.dev worker]
  worker --> verify[Verified website revision]
  verify -->|Current explicit push or publish to OWNER/REPO| gate[Check signed-in account, ownership and write permission]
  command[Native /me3 push or publish REPO] -->|Resolve account and latest website in this chat| gate
  gate -->|Verify manifest and recheck revision| git[Temporary local Git repository]
  git -->|Non-force git push| github[GitHub bmo-pages branch]
  github -->|Publish request only| pages[Configure Pages through gh]
```

The explicit, destination-bound request is the authorization for an account-owned
push. There is no second terminal or web dialog. The host checks `gh api user`
and the canonical writable repository; login alone never triggers a push. Workers
cannot upload files. Only the verified site snapshot goes into Git, not the
project worktree. Plain push leaves Pages settings alone; publishing also sets
its source. An unchanged snapshot reuses its commit.

### D3 / R11 · Implemented live website canvas

```mermaid
flowchart LR
  voice[Portfolio research request] --> pi[Pi research worker with Brave]
  pi --> review[Operator selects sourced facts] --> site[Website job and revision]
  site -->|Draft HTML| renderer[OpenIntelligentUI] --> embed[Sandboxed canvas iframe]
  site -->|Verified site bundle| embed
  site -->|Same approved revision| pages[R10 GitHub Pages publication]
```
