# Architecture review

### D1 · Local BMO voice session

```mermaid
flowchart LR
  mic[Mic] --> asr[Deepgram]
  asr --> turn[Local turn controller]
  turn --> pi[Project Pi session]
  pi <--> model[OpenRouter]
  pi --> tts[Local BMO Piper and speaker]
  pi --> jobs[Local job supervisor and workers]
```

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

