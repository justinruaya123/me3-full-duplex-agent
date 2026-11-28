# Implementation and qualification status

## November 28 · Production PDF retrieval (D4 / R10c)

The handoff branch adds local English OCR to PDF ingestion. The normal file CLI
indexed all four frozen lecture PDFs (138 pages, 142 passages). With native
text, the top four results contained every required page for 4/13 questions
and covered 8/23 evidence requirements. With OCR enabled the same queries
reached 7/13 questions and 13/23 requirements. Indexing on this Mac took 0.16 s
and 48.13 s respectively. These are retrieval scores. Answer quality and
Raspberry Pi timings require separate runs.

In a separate project-folder launcher check, a previously unseen three-page
scan returned the unique requested page and reopened its original citation.
Regressions cover an OCR-only phrase, changed source bytes, a missing engine,
atomic refresh failure, native-only indexing and an index built with the older
schema. The installed handoff checkout passed 508 v1 and 538 full Python tests,
114 Node tests and five duplex simulator checks. Both Python suites and the
Node suite had zero skips. Compilation passed.

[Production ranks](evidence/2026-11-28-rag/production.json) · [Reproduction](evidence/2026-11-28-rag/README.md) · [Setup on another computer](SETUP.md#local-document-retrieval)

## November 21 · Account-owned Git push (R10, current)

An explicit `/me3 push REPO` or `/me3 publish REPO` uses the active `gh`
account; it no longer opens a second approval prompt. The host verifies
ownership, write permission, the current job revision and manifest. It runs
a real non-force Git push to `bmo-pages` from a temporary worktree. Only a
publish/Pages request also configures Pages. This supersedes the earlier
approval-popup behavior described below.

A live read-only `gh api user` identified the active account. A real Git
transport test against a temporary bare repository covered initial push,
unchanged retry, fast-forward update and removal of an obsolete asset.
GitHub ownership, permission denial and Pages configuration paths used stubbed
API responses. No remote repository was modified in these checks. Installed
verification passed 515 Python tests (485 versioned) and 113 JavaScript
tests, zero skips, plus the five duplex simulation checks and compilation.

## November 21 · Direct native GitHub Pages approval (R10, historical)

`/me3 publish OWNER/REPO` now selects the newest website in the current Pi
chat without model inference. It refuses an unfinished site or a web-stream
session and uses Pi's native confirmation. Existing revision, file hash and
explicit approval gates are shared with conversational publication.

A real project Pi process in a PTY resumed the current chat, resolved its
completed website, displayed the native confirmation for a test destination,
and accepted Escape to cancel. This was a local approval-path smoke test;
no GitHub API calls or live deployment were made during the smoke. Installed
checks passed: 515 full-suite Python tests, 113 JavaScript tests, five duplex
simulator checks and Python compilation, with zero test skips.

## November 21 · Timely website research and explicit GitHub push (D3 / R10)

Recent Pi errors rejected “push it to GitHub” before they opened an approval
prompt. A push request can now name the exact repository in the same turn
without saying “GitHub Pages.” Missing or mismatched destinations,
negated requests, and conversational approval still cannot reach GitHub. A
matching request presents the verified files and destination for interactive
approval; the real Pi terminal continues to use its native prompt.

For recognized website requests needing current public information, the
client sends the scoped public subject to Brave before it submits the build.
The worker receives bounded source material. Named local pages can use
verbatim copy from the current request; browser verification checks that
supplied copy is present and that unrelated personal claims are not added.
A name-only request with no further authorized copy remains a starter.

A live Brave smoke on a synthetic website request returned five URLs.
Publisher regression tests used a stub GitHub API and verified zero API calls
before approval. `gh auth status` succeeded; no live upload or deployment
was attempted. The named-page test used fixture inference and real offline
browser verification. Installed checks passed: 515 Python tests (485
versioned), 112 JavaScript tests, five duplex simulation checks and Python
compilation, with zero test skips. No microphone or acoustic checks were
performed.

## November 21 · GitHub Pages approval in the BMO window (R10)

The companion window presents a native Publish / Cancel dialog over the
current view instead of relying on the streamed Pi terminal. Terminal-only
sessions still use Pi's prompt. The local client binds the decision to the
pending request, checks expiry, and rechecks the turn and verified revision
before calling GitHub.

A headless Chromium test on the Pi exercised the actual loopback WebSocket,
including reconnect with an unanswered prompt, Escape to cancel, and Publish.
Additional tests used fixture decisions and a stubbed GitHub API. No live
GitHub upload, deployment, or acoustic test was run for this change. Installed
verification passed 513 Python tests (483 versioned), 111 JavaScript tests,
five duplex simulation checks and Python compilation, with zero test skips.

## November 21 · BMO questions and Pi requests on Raspberry Pi 5 (D3)

BMO no longer forces a lookup just because a question contains words that are
absent from the chat. Pi judges ordinary stable facts; explicit freshness and
rechecks retain the public-query gate. The host schedules the cached “Searching.”
only at live fetch, not for a cache hit or an ordinary Pi task. A commitment tone
no longer suppresses that cue. User speech or an available answer can preempt it.

Four fresh typed Pi sessions on the board used the configured live foreground,
with memory off and an empty operator profile. A capital question and a polite
rephrasing request used zero tools. A release-version question and a request for
a periodical’s exact issue number each called `web_lookup` once. Both replies
reported what they could not verify. These observations test routing, not general
confidence calibration or the accuracy of every statement. The Piper clip was
generated locally; post-tone playback was tested with a digital callback, not
through the physical microphone and Bluetooth speaker. On the Pi, 511 Python
tests passed (481 in the versioned suite) and 105 JavaScript tests passed, with
zero skips. All five duplex simulation checks and Python compilation passed.

## November 21 · Wake latency and end-of-turn feedback

Five mic wake attempts were transcribed as variants of the name and went to
Pi for a conversational answer. The three cached greetings also started with
344–600 ms of quiet. Confirmed wake-only turns now play a trimmed local clip.
A finished request can receive one 85 ms acknowledgment sound while Pi
answers. An ordinary pause, a stutter and a wake embedded in a request have
separate regression cases.

The Mac replay used newly synthesized input, the class digital rig, live
Deepgram Nova-3 and OpenRouter, and local BMO Piper. Each run used the same
three phrases and an empty private profile. The times below start at the local
VAD end and stop at the first output callback containing the indicated audio.

| Input and measured output | Before | Updated replay 1 | Updated replay 2 |
| --- | ---: | ---: | ---: |
| “Hey BMO” → spoken greeting | 2,498 ms | 499 ms | 440 ms |
| “What is seven plus five?” → first sound of the spoken answer | 3,159 ms | 1,240 ms | 1,102 ms |
| Same question → acknowledgment sound | — | 703 ms | 622 ms |
| “Um” → dispatched turns / output clips | 0 / 0 | 0 / 0 | 0 / 0 |

Both updated answers were “Twelve.” The acknowledgment began 160 and 161 ms
after the controller committed the request. Counting instead from the last
voiced input sample to the first returned sound on the rig clock, the wake
took 1,653 and 1,873 ms, and the question took 921 and 841 ms to its tone.
A third session repeated the wake after the question and hesitation. On
the rig clock, the first greeting took 1,493 ms and the repeat took 755 ms.
On the local VAD clock these took 382 ms and 538 ms. “Twelve” started
1,080 ms after VAD end and “Um” again produced no output.

Before the standby connection change, a digital run lost its second turn to
a two-second capture overrun. The Mac mic also overran when a final flush
took 707 ms and the next handshake blocked capture for a further 1,884 ms.
The client now starts one standby handshake during speech. A regression
holds the old final open and verifies that the new connection cannot take
its audio or transcript. Both tabulated runs completed all three inputs
with this change. In two minutes on the physical Mac mic, eleven utterances
opened and the device reported zero overruns. The longest wait for an ASR
connection at speech onset was 1,015 ms. This observation counts audio activity without grading the
speaker's words or replies. The samples do not establish a p95 or physical
microphone-to-speaker latency. [Current voice path (D1)](ARCHITECTURE_REVIEW.md)

## November 21 · Public questions and foreground computer use

The Mac mic transcript contained a complete question about a person. Pi
offered to look them up, then the local resolver rejected both a confirmation
after a wake turn and a spoken spelling correction before contacting Brave.
An unanswered public question now initiates a lookup. A follow-up can carry
a recently supplied public name, and the current transcript supplies a corrected spelling.

In a fresh project Pi session with an empty owner profile and live OpenRouter,
“Who is Tim Berners-Lee?” returned five Brave Web sources in 6.19 s. After the
name Fe del Mundo was introduced, “Where did she study medicine?” returned
five sources in 3.40 s. “What was her name again?” used the chat in 0.54 s
with zero tool calls. These are individual typed turns measured through the
final reply. The configured route used Brave Web with Pi summarization.

A fresh Mac operator session loaded eight desktop tools from the pinned Pi
computer-use extension. The local arm64 helper responded on protocol 6.
Both Accessibility and Screen Recording were off during preflight. No native
desktop observation or input was exercised. Raspberry Pi hardware is untested.

## November 21 · Name-only website in project Pi

The Mac microphone transcript captured “Can I create a website about myself?”
The original session asked for details, then reported an empty search after a
local tool rejection. Brave received no request from that tool. Pi now uses
the current conversation and private profile to supply a design brief and
display name. A proposed public lookup can ask permission using the known
name. The local worker owns layout and the host verifies the archive.

Two fresh typed replays through the configured OpenRouter foreground and Pi
worker used a fictional profile. The original question and “Make a website
about my name” each produced one website submission, zero searches and a
downloadable ZIP verified at 1280×800 and 390×844. Earlier prompt iterations
asked a follow-up and earlier builds failed verification. A keyboard-focus
regression covered the generated skip link. The queued acknowledgments
described planned copy that the verified name-only pages omitted. These
replays did not measure acoustic turnaround.
## November 21 · Speech stop and delegated-task cancellation

Local audio and supervisor regressions exercise a buffered reply, a late answer
replacing a cue, and a blocked worker with a second job queued. The speaker
pauses at voice onset. A finalized “stop” clears the buffered reply. The Pi
extension consumes the command silently. A committed “stop current task” on
the live microphone path requests cancellation for one job. Interim revisions,
stale commits, recorded input and unconfirmed overlap cannot cancel jobs.

Four generated audio clips went through live Deepgram Nova-3 and the Mac voice
entry point with local Silero and SmartTurn. Both BMO Piper and macOS Samantha
produced “Stop.” and selected the speech-only control. For “stop current task,”
Samantha produced the exact final and selected the task control. Deepgram heard
the BMO clip as “Subcurrent task.” and selected no control. These were fixture
inputs with the supervisor disconnected. The worker-cancellation result comes
from the separate local regression. Physical microphone timing and Raspberry Pi
performance remain unmeasured for these commands.

The installed Mac checkout passed all 498 Python tests, including 468 versioned
tests, and all 102 JavaScript tests, with zero skips. The five duplex simulation
checks and Python compilation also passed.

## November 21 · Current chat, Brave results and edits to ongoing work

The Pi extension previously inserted three old chat excerpts beside a new
message even when none matched. During an active conversation, the ordinary
follow-up now uses the current branch. Explicit cross-chat recall and the
private owner profile are available. Recent Brave excerpts can support a related
follow-up without another confirmation. The old requirement to quote a full
source sentence verbatim on a recheck was removed.

A seven-turn typed Mac session used the project Pi, live OpenRouter, live Brave
and a real local worker. It delegated a packing checklist, answered a question
about Mars, expanded the answer and displayed five linked results for the
requested mission page. A spoken-style edit to the checklist advanced the same
job from revision 1 to 2. A separate arithmetic question returned 13 without
tools. The status tool then read the completed revision containing the headlamp
edit. No turn asked the operator to restate the subject. An independent public
sports question triggered Brave without an explicit request for a search.
Brave Answers returned an entitlement refusal on the configured account. Brave
Web supplied five sources and Pi produced the summary.

The original three input WAVs passed all five digital routing checks again.
On this Mac replay, local VAD end to the first task-specific speaker callback
was 4.260 s for the accepted checklist, 2.207 s for “12” and 2.814 s for the
status of the same completed job. The worker saved a three-step checklist under
60 words. These are individual digital measurements. Target-device and physical
microphone timing remain open.

Chromium exercised an actual result anchor in the companion panel and both
display themes. The 13 original frames passed their pinned hashes. Without
the optional pack, captions and status still work. The active catalog contains
12 BMO speech clips, including the single listening cue “I'm listening.”

Installed Mac verification passed all 494 Python tests, including the 464
versioned tests, and all 101 JavaScript tests. Both suites had zero skips.
The five duplex simulation checks and Python compilation passed.

## November 21 · Three-turn spoken routing on the Mac

The same three input WAVs that previously scored 0/4 were replayed byte for
byte through the class digital transport, live Deepgram, the project Pi
foreground on OpenRouter, a real local Pi worker and local BMO Piper.
The local controller committed each request once. The worker saved a three-step
checklist under sixty words. The arithmetic reply was “12” with zero tool
calls. The status tool returned the original job ID at revision one, completed.
All five checks passed, including a reply playback receipt for each turn and
the saved draft. This is a digital transport run on a Mac.

| Turn | Time from local VAD end to the first task-specific speaker callback |
| --- | --- |
| Draft accepted, “On it.” | 3.427 s |
| Arithmetic answer | 2.430 s |
| Completed checklist status | 4.096 s |

The earlier acoustic classifier could hold a finished request until timeout.
Forcing Deepgram to finalize at the first quiet frame could also lose a
sentence-ending marker. An intermediate repair submitted a second job from a
trailing qualifier. The controller now preserves short sentence gaps, considers
settled words and provider endpoint timing, and checks the final before dispatch.
The installed Mac suite passed 489 Python tests and 98 JavaScript tests with
zero skips. The versioned Python subset passed 459 tests. The duplex control
simulation and compile checks passed. Physical microphone timing and Raspberry
Pi performance require separate measurements.

## Consolidated side-chat integration

A live three-prompt typed Pi smoke test submitted one draft, answered the
unrelated arithmetic turn without tools and retrieved the same job.
Two digital runs disconnected during playback. The upstream rig suppressed
a missing SciPy import during 24-to-16 kHz resampling. With the benchmark
dependency installed, all three recordings completed. The floor controller
discarded two unfinished turns, the remaining status query found no delegated
job, and the run passed zero of four spoken-routing checks. The control simulation
preserved a running job across speech interruption. Physical microphone timing
and Raspberry Pi qualification remain open.


## November 21 · Project-local Pi portfolio research and export

A typed Mac Pi replay of “make me a portfolio website and look up my work” invoked the separate research worker. Its only tool was the pinned pi-web-search Brave search. The first personal query included several work-related keywords and returned no usable evidence. A fresh run using the approved public name returned three sourced candidates. The operator selected two. The local website job created a ZIP containing those two facts, their links, the stylesheet and a GitHub Pages marker. The archive passed CRC and file-hash checks. Isolated Chromium loaded the export under a repository subpath at 1280 × 800 and 390 × 844 with external requests blocked. Both sizes showed the selected facts without horizontal overflow or page errors. The run exercised live OpenRouter and Brave, the Pi extension, fact selection, the supervisor and static export. Microphone capture and GitHub deployment were outside this replay.

The installed Mac Python suite passed 314 tests, including 284 versioned tests. All 71 JavaScript tests passed. Both suites had zero skips. The duplex control demo and Python compile check also passed.

## November 21 · Fresh verification after a spoken correction

The Sri Lanka microphone trace recorded six lookup tool attempts and zero Brave responses. The foreground inserted a year the speaker had not supplied. The local resolver repeatedly asked the speaker to confirm that guess. On the next turn BMO answered from memory.

In a fresh, isolated Mac Pi session, replaying the two committed transcripts as text produced two live Brave Web receipts, five sources each. Neither turn explicitly asked for search. The second query used the public question from the first receipt and requested recent developments. The final reply was “I checked again, but I couldn’t confirm that from the sources I found.” An intermediate build had claimed that no newer event occurred. The final version accepts a complete source sentence for that kind of recheck or reports the uncertainty. This test covered the Pi foreground, OpenRouter and Brave Web. Microphone capture, physical playback and Brave Answers were outside this replay.

Installed Mac verification passed 313 Python tests including 283 versioned tests, plus 65 JavaScript tests, with zero skips. The duplex control simulation and Python compile check passed.

## November 15: lightweight owner-scoped text memory

Added opt-in runtime memory, separate from the coding assistant's Pi memory.
`ME3_MEMORY_ENABLED=1` uses a private mode-0600 SQLite file under the existing
state directory, with no new dependencies, embedding service or third model.
This checkout's ignored `.env` enables it for the next normal launch; provider,
speech, account and ownership settings were not changed. No personal facts or
old coding-agent conversations were imported.

Accepted committed owner turns and software-receipt-confirmed assistant clauses
are retained across session end/restart. Partial/stale/unverified input and
unknown/cancelled playback are excluded. Facts/projects require explicit owner
commands; the model cannot write its own beliefs into memory. Retrieval is
bounded keyword/recency data, not instructions, action approval or job truth.
Foreground context includes live owner-filtered task status; workers receive
only relevant saved notes, not the conversation archive. Static website
validation and job revisions remain unchanged.

Per-owner bounds are 64 notes, 32 sessions and 256 messages, with 4,000-character
message excerpts. Foreground/worker memory context caps are 7,500/2,500 JSON
characters. `/memory`, `/remember`, `/project`, `/recall`, `/forget` and
`/memory on`/`off`/`clear` expose inspection, correction and privacy controls.
Forgetting also removes literal repetitions and fences that owner's active
foreground context, without cancelling jobs. Whole-memory deletion pauses
retention but does not erase job artifacts, harness sessions, backups or text
already sent to a provider. Course and explicitly opted-out sessions neither
use memory nor receive memory-change interruptions.

RED tests preceded implementation and reproduced storage-error misreporting,
opted-out-session interference, failed-startup lock leakage, shutdown blocking
and persistence failures undoing playback receipts. Those regressions are fixed.
Final verification in the installed `.venv-pi` checkout:

- **20/20 memory tests**, zero failures/skips, 0.289s.
- **211/211 v1 tests**, zero failures/skips, 14.324s.
- **241/241 full-suite tests**, zero failures/skips, 16.484s.
- Final test logs contain no unclosed-resource or unawaited-coroutine warnings;
  memory tests explicitly enable ResourceWarning reporting.
- `python -m me3.duplex_demo` and compilation of `me3`, `tests` and
  `integrations` passed; `git diff --check` passed separately.

These are local SQLite/control tests, fixture inference, actual static syntax
checks and a Pipecat in-process transport regression. No successful live
provider call, microphone test, acoustic latency/AEC measurement, new benchmark
score or target-hardware qualification is claimed. Existing speech auth and
normal ownership prerequisites remain unresolved here. Details and deletion
limits are in [MEMORY.md](MEMORY.md); earlier implementation evidence follows.

## November 7: explicit Pi-fast foreground demo profile

At operator request, `ME3_FOREGROUND_PROFILE=pi-fast` now selects a separate
local Pi agent for conversational inference instead of Qwen/Nemotron. Worker
jobs retain their independent Pi sessions. Mic/speaker and orchestration remain
on the Pi; Mac ASR/TTS settings are unchanged. This is an explicit alternative
to the November 4 foreground selection, not a fallback or third LLM role.

The warm foreground subprocess has tools/resources disabled, an in-memory
session and independent cancellation. Each turn resets context, checks the exact
provider/model, requests thinking `off`, checks supported levels and effective
state, then streams text deltas. Reasoning/tool events, mismatched final text,
provider errors, unsettled/aborted runs, deadlines and early stream closure fail
explicitly and reap only that foreground child. Runtime shutdown closes it.
No realtime/provider latency guarantee follows from these settings.

RED fixtures preceded implementation. Final installed verification: **191/191 v1
and 221/221 full tests**, zero failures/skips; simulator and compilation passed.
Ten new foreground tests use subprocess fixtures, not real inference. Additional
fixture variants initially failed due to incorrect test-string substitutions;
those fixtures were corrected and rerun. Final runs have no resource warnings.
The earlier 218-test run predates the three additional failure-path regressions.

Ignored `.env` explicitly selects `pi-fast`, `openai-codex/gpt-6.1-sol` for the
foreground and is mode 0600. Real inference was attempted twice but rejected for
missing credentials in the isolated `.local/pi` auth store. Protocol preparation
accepted and reported thinking off before the prompt; no actual successful model
response or inference latency is claimed. The unrelated default Pi login was
not copied, reinterpreted or substituted. Mac speech auth and normal ownership
settings remain blocked as recorded below. No demo server has been left running.
See [setup](SETUP.md#explicit-pi-only-llm-demo-profile-november-7).

## November 7: Raspberry Pi local launcher check

`scripts/me3.sh` now selects the installed `.venv-pi` on Linux for doctor,
console and local microphone/speaker voice mode; the separate Mac speech
interpreter is unchanged. Plain `.env` assignments are exported to children.
Pi worker orchestration and the fast Qwen foreground controller remain local;
only configured inference requests leave the host.

Launcher regressions first reproduced missing Mac interpreter failures for all
three Pi modes. Installed verification after the fix: **181/181 v1 tests** and
**211/211 full-suite tests**, zero failures/skips. These include three launcher
fixture tests, not provider or acoustic tests. Control simulator and compilation
also passed. Logs are local under `.local/demo-check/`.

Live launch was attempted and exited explicitly with missing foreground
BASE_URL/model configuration; no runtime was left running. The Qwen profile is
selected but endpoint/model/key are empty. The configured Mac speech listener
at port 8002 was reachable but returned HTTP 401 with the configured ASR token.
Wake phrase and independent speaker-verifier settings are also absent. No live
voice, speech inference, physical AEC or end-to-end hardware acceptance is
claimed by these checks.

## November 7: published Turbo-constrained build and canonical ME3 validation

The published branch is `main`, including `hermes/benchmark-latency-v1` and its
committed evidence without rewriting that history. The final measured build
is `6bbbfd57d5e5c062ec3846762158118a7318b0db`; subsequent evidence/documentation
commits retain its runtime code. Pi.dev remains the default local worker and the
controller remains harness-neutral. The operator's exact Whisper Turbo constraint
is retained: `mlx-community/whisper-large-v3-turbo`. Qwen, Kokoro/`af_heart`,
credentials, billing configuration and the external scorer were not substituted.

The unchanged canonical ME3 benchmark `57eaddbc188ce9a19b8fd002b575f703426956f4`
with the complete official dataset ran seed 231, ten phrases x three runs and
three complete duplex rounds. Run `2026-11-07_06-10-46` completed **60/60 queue
items / 72 recordings**, zero transport/scoring errors, in **1357.089s**.
Every recording, including clean twins, received a fresh local runtime through
the official assistant/reset hooks. The global course ownership bypass is
explicit. No custom subset, development prompt pilot or simulator is used as
benchmark acceptance evidence.

| Metric | Mean | p95 | ME3 target | n | Observation |
| --- | --- | --- | --- | --- | --- |
| E2E, VAD end to output mark | 2.552s | 3.711s | 4s | 29 | Below on observed samples |
| ASR final | 1.470s | 2.036s | 0.8s | 30 | Over |
| LLM first text | 0.402s | 0.745s | 1.5s | 29 | Below on observed samples |
| TTS first PCM | 0.424s | 0.696s | 0.6s | 29 | Over |
| Interruption stop | 0.337s | 0.406s | 0.8s | 3 | Below on observed samples; n=3 is insufficient |
| Corpus WER | 3/207 = 1.449% | Not applicable | 15% | 30 | Below |

There were **29/30 recorded phrase replies**. The scorer excludes missing stage
measurements; those exclusions are not passes. Recorded digital speech onset
mean/p95 was **3.066/4.158s** over 29 replies, distinct from the output-mark clock.
Six interruption cases were scheduled, but only three had valid stop timing;
already-silent cases are not assigned zero latency. The sampled stop result
does not establish a reliable p95 or the specification's 250ms acoustic gate.
The maximum E2E/LLM samples, 6.304s/4.609s, remain in the reports.

Behavior remains incomplete: turn-taking TOR **1/3**, interruption TOR **2/3**,
false-turn rate **2/6** under the scorer's word threshold, and no counted speech during
the three synthetic and three Candor pause windows. Four of six false-turn recordings contain detected bot speech, including short
replies below that threshold. That rate does not establish rejection of
non-addressed speech. Backchannel trials returned in **2/3** cases and one
stayed silent. The previously stalled first-round acknowledgement returned after
**1.832s** while remaining provisional; broader acknowledgement semantics remain
unqualified. Content relevance/Respond/Resume labels and UTMOS are unscored.

Implemented and tested increments:

- `a8dbd9c`: owner-only, instance/generation-fenced benchmark resets with bounded
  launcher group cleanup and fresh log/runtime directories. This explicit
  benchmark process reset is separate from ordinary voice-session lifetime.
- `fc3e0c1`: resolve entirely empty final recognition without a transcript or
  action; fence late empty results and deferred stops after resumed speech.
- `1271346`: reuse the selected Turbo decoder's full-context encoder features
  for confident automatic language detection. Below 0.95, use the original
  detector input without evicting decode features. The padding is a changed
  heuristic, not universal language/quality equivalence. Twenty native generated
  development pairs retained text/language/all word fields. Seventeen warm
  ordinary pairs averaged 1.824s -> 0.978s; ambiguous and cold observations are
  retained separately. No English default or smaller ASR was selected.
- `c5292c0`: preserve decimals, dates, versions, titles and source words across
  token partitions and bounded clause cuts; indivisible oversized tokens fail
  explicitly rather than emitting fragments.
- `c321634`: CPU-development VAD onset settings reduce quiet-speech delays while
  retaining SmartTurn, ownership and action gates. Synthetic development onset
  p95 was 393ms over 135 correlated variants; 66s of artificial negatives is
  insufficient speech/echo/false-interruption qualification.
- `cd9232f`: an ended, wholly affirmative acknowledgement can resume retained
  audio without semantic commitment, a new request, history entry, job approval,
  cancellation or epoch change. All earlier hypotheses can veto this relaxation.
  Transport-observed PCM, current delivery rights and question lifetime guards
  prevent startup, pending-answer and stale-result misclassification.
- `6bbbfd5`: publish the planned Raspberry Pi pull/setup/ME3 procedure and the
  verified Sol model example. Actual ARM installation/device tests remain unrun.

Final installed verification: **208 passed, zero failures, zero skips**, 14.958s;
the required v1 subset passed **178/178, zero skips**, 10.532s. Demo, compilation
and changed-Python lint pass separately. The new floor tests include five actual
Pipecat fixtures with fixture inference; they are control/transport evidence.
Actual native/HTTP speech passed **6/6** checks earlier on the same speech model
code. Current real Qwen and Sol inference plus local Pi RPC passed. Overall
normal-voice doctor readiness remains false because the wake phrase and an
independent speaker/overlap/addressee verifier are absent.

Small TTS scalar/voice-cache probes and a decoder compiler candidate were not
promoted: the latter had an 8.151s cold invocation and changed observed PRNG
continuation. Two real-Qwen short-sentence prompt pilots completed their protocol
but failed manual quality gates. The original foreground prompt and Kokoro
inference path are retained. These are rejected development experiments, not
alternative benchmark scores.

**Next unpassed acceptance gate:** ASR final mean/p95 <=0.8s while retaining
Turbo; current native ordinary inference is about 0.98s and final scheduling adds
queue delay. TTS p95 <=0.6s also remains open. Broader semantic endpointing,
acknowledgement/addressee handling, long turns, busy-worker speech, content/MOS,
physical acoustics/AEC, actual Raspberry Pi installation and the 30-minute soak
remain unpassed. Mac direct-feed results do not qualify those gates.

Evidence: [complete iteration archive](evidence/2026-11-07/realistic-targets/README.md),
[canonical ME3 results](BENCHMARK.md), [setup/launch](SETUP.md) and
[planned Raspberry Pi procedure](RASPBERRY_PI_TESTING.md). The earlier
continuous-session measurements below are preserved with their original scope.

## November 7: benchmark-driven inference improvements

On `hermes/benchmark-latency-v1`, commits `87c3336` and `03e1ff7` improve the
selected models' inference path. Exact Qwen/Whisper/Kokoro IDs, local speech
weights, voice, credentials and the external scorer are unchanged. Remote
Qwen weights are provider-managed; its exact response model ID is checked.
Pi remains the default
worker and the controller remains harness-neutral.

Native profiling found three ~0.9s Whisper encoder evaluations per request.
Decode and word alignment receive byte-identical mel inputs. Request-local
reuse removes that duplicate evaluation, preserves automatic language detection
and word timestamps, and releases input/features on every exit. Six paired
real GPU checks on generated development speech fell from 2.838s to 1.937s mean
(31.76%); transcripts, language and every word timing/probability were identical.
Capture also reuses recognition for identical full PCM in the same generation;
final commitment still requires SmartTurn approval. Changed audio, new
generations, invalidation and close fence/erase that memo.

The actual optimized run `2026-11-07_02-16-38`, frozen at `03e1ff7`, completed
40/40 queue items / 44 recordings in 797.847s, with zero transport/scoring
errors. Same benchmark `57eaddbc`, seed 231, 10 phrases x 3 runs plus one
duplex round, same global course bypass and six-second gaps:

| Metric | Baseline mean / p95 | Optimized mean / p95 | Target |
| --- | --- | --- | --- |
| E2E, VAD end to output mark | 5.422 / 6.788s | 3.639 / 5.077s | 4.0s |
| ASR final | 4.454 / 5.231s | 2.786 / 3.546s | 0.8s |
| LLM first text | 0.335 / 0.890s | 0.153 / 0.117s | 1.5s |
| TTS first audio | 0.422 / 1.013s | 0.471 / 1.122s | 0.6s |
| Barge-in stop, n=2 each | 0.380 / 0.380s | 0.748 / 1.022s | 0.8s |
| Corpus WER | 4/207 = 1.932% | 5/207 = 2.415% | 15% |

E2E mean improved 32.89%, ASR final mean 37.46%. All 30 phrase trials had
recorded replies, versus 28/30 before. Optimized software stages have n=30;
baseline E2E/LLM/TTS have n=29. Recorded speech onset mean/p95 improved from
5.836/6.982s to 4.151/5.524s. The extra WER edit occurred in the same career
phrase that varied across baseline repetitions; no benchmark-specific text
correction was added. Native output equality is separate from whole-pipeline
WER. Provider and host load were uncontrolled between runs; LLM/TTS code was
unchanged, so their variation is not attributed to encoder reuse.

Duplex results remain mixed: interruption TOR 0/1 -> 1/1; turn-taking TOR
1/1 -> 0/1 (a three-word acknowledgement did not count); false turns remain
2/2 and pause TOR remains 0/1 in each pause group. One backchannel trial stopped
without returning. A slow interruption's mapped trace suggests ~0.922s before
VAD start and ~0.130s from that mark to old output ending; this is one digital
case, not acoustic qualification or justification to tune on a held-out clip.
No judge/UTMOS score, physical acoustic p95, busy-worker or Pi claim is made.
The unchanged six-second-gap protocol still permits context/capture carry-over.

RED/GREEN tests preceded both changes; each stage passed the installed suite.
The final suite is **141 passed, zero failures, zero skips**, 4.475s. Actual
authenticated HTTP speech passed 6/6 checks, including word timestamps and
concurrent ASR/TTS. Independent read-only review found no remaining
Important/Critical findings in the changes. Evidence and unchanged official
reports are in [latency improvement evidence](evidence/2026-11-07/latency-improvement/README.md).
After task resumption the unchanged source passed **141/141 again, zero skips**,
4.622s; the local speech service was found stopped after the interruption,
then restarted and its exact-model catalog verified.

**Next unpassed gate:** ASR final <=0.8s, E2E p95 <=4s, TTS p95 <=0.6s and
reliable interruption p95 <=0.8s. Current native ASR still takes about 1.9s;
further streaming/compute work is required. Detector/addressee qualification,
fresh-session resets, long-turn stitching, meaningful response quality and
larger independent samples remain open, along with the spec's acoustic targets.

## November 7: real course benchmark completed; latency gate not passed

The unchanged external benchmark at `57eaddbc188ce9a19b8fd002b575f703426956f4`
ran actual Mac Whisper/Qwen/Kokoro inference on agent `1168478`. Seed 231,
10 phrases x 3 runs and one duplex round completed all 40 queue items in
807.262s: **44 recordings, zero transport errors and zero scoring errors**.
Real `faster-whisper/small` CPU-int8 evaluation and Praat voice features ran.
No microphone or physical speaker was opened. The older benchmark checkout
and all failed attempts are preserved; nine external score hashes match.

| Metric | Target | Mean | p95 | n | Upstream result |
| --- | --- | --- | --- | --- | --- |
| VAD end to output mark | 4.0s | 5.422s | 6.788s | 29 | Over |
| ASR final | 0.8s | 4.454s | 5.231s | 30 | Over |
| LLM first text | 1.5s | 0.335s | 0.890s | 29 | Met |
| TTS first audio | 0.6s | 0.422s | 1.013s | 29 | p95 over |
| Barge-in stop | 0.8s | 0.380s | 0.380s | 2 | Met on two samples |
| Corpus WER | 15% | 1.932% | Not applicable | 30 | Met |

Four edits / 207 reference words; two of 30 phrase trials had no recorded
reply. Missing stage timings are excluded by the scorer, not passes. Actual
recorded output speech onset was 5.836s mean / 6.982s p95 over 28 trials.
These software/direct-feed clocks are separate from physical acoustics.

The first full attempt crashed when a resumed turn filled the ASR queue behind
native inference. Regressions reproduced two orderings. Commits `9c1064e` and
`1168478` retire superseded queued finals/partials without cancelling the native
lock holder, freeing capacity prematurely or weakening duplicate-final overflow
protection. Both RED/GREEN traces are retained. The final actual run had no
disconnections. Independent read-only review found no remaining
Important/Critical issues in that fix. Commit `4ec8997` adds optional accepted
ASR and validated LLM stage marks; partial/stale text cannot become final marks.
Fresh installed full suite after the final run: **136 passed, 0 failures,
0 skips**, 4.190s. Demo, compilation and lint are checked separately.

**Remaining failures/limits:** false-turn speech occurred in 2/2 sampled
side-talk/TV trials; v1 interruption TOR was 0/1; backchannel/background return
gaps were 5.096s/6.020s. The course profile globally bypasses ownership and
treats committed speech as addressed. Default six-second gaps carried earlier
speech/incomplete capture into later trials; accumulated capture hit the 16s
cap once and was discarded. This is a diagnostic continuous-session baseline,
not independent per-clip ownership/turn qualification. Long dictation remains
unimplemented. No relevance or v1.5 content judge was configured; UTMOS was not
installed/scored. Voice-change statistics have one pair and no significance
claim. Barge-in has only two samples. No physical Pi, acoustic p95 or busy-worker
run is claimed. The upstream report's fixed Raspberry Pi title is a template;
its measured device card is Darwin/16GB.

**Next unpassed acceptance gate:** reduce accepted ASR final delay and repeat
the pinned test to meet ASR <=0.8s and E2E <=4s at mean and p95, with TTS p95
<=0.6s. Independent trials additionally need a hard session reset, qualified
addressee/overlap handling, more rounds and a configured content judge. The
spec's 1s/250ms acoustic targets and Raspberry Pi qualification remain unpassed.
Reports, exact commands, source pins, failure receipts and test counts are in
[course benchmark evidence](evidence/2026-11-07/course-benchmark/README.md) and
[BENCHMARK](BENCHMARK.md).

## November 7: speech models and service verified

Whisper `mlx-community/whisper-large-v3-turbo` and Kokoro
`mlx-community/Kokoro-82M-bf16` / `af_heart` pass actual native and authenticated
HTTP inference. The earlier November 4 stalls did not reproduce in these bounded
GPU runs; those failed receipts remain historical failures. No model substitution
or provider/billing change was used.

Changes in `2fdc48e` and `047c4ec`:

- Startup generates and recognizes a known phrase before binding the HTTP
  listener. Failed warm-up closes resources and cannot advertise readiness.
- Empty or malformed first TTS audio is rejected before HTTP success. RED
  regressions reproduced empty audio returning HTTP 200 and malformed framing.
- `./scripts/me3.sh speech --check --output .local/voice-check.wav` performs a
  real synthetic TTS-to-ASR check and saves an optional 24kHz WAV sample.
- A parent owns the native speech process. Startup/self-check deadlines are
  90 seconds with bounded process-group cleanup; shutdown kills/reaps stuck
  native threads. Self-check output is capped at 64KiB while it is read.
  Review reproduced and regressions now protect blocked native work, descendants
  holding stdout and excessive output. Independent review found no remaining
  Important/Critical issues in the fix pass.
- A private local speech token and matching ASR/TTS client keys were configured
  in ignored mode-0600 `.env`; foreground and Pi settings were preserved.

| Verification track | Observed result |
| --- | --- |
| Actual native GPU and exact models | Final cold self-check recognized its 2.6s generated phrase; 13.134s total |
| Actual authenticated HTTP speech | 6/6 checks passed, including unauthorized/model rejection, word timestamps and concurrent ASR/TTS |
| Warm HTTP samples | TTS first PCM 0.290s / 0.501s; ASR 2.721s / 2.786s |
| Concurrent HTTP sample | Both completed; TTS first PCM 2.003s, ASR 2.934s |
| Actual Pipecat/VAD/SmartTurn/Whisper/Qwen/Kokoro | Generated question produced audio for “That's 42.”; 91 input frames continued during output |
| Live 12s window | No speech detected; operator reported hearing the cue but missing the window; not passed |
| Live 30s open-mic retry | Numbers recognized and audio sent to headset, but expected completed answer not confirmed; operator heard another/clipped reply; not passed |
| Live single-turn retry | 480,000 frames in the 30s window but no detected speech/model response; operator reported missing that window; not passed |
| Manual-start single-turn live test | **Passed**: question numbers recognized, complete 42 reply sent; operator confirmed a clear/complete answer and reported excessive latency |
| Fresh installed full suite | **131 passed, 0 failures, 0 skips**, 5.601s |
| Guarded service shutdown | Parent exited successfully; listener closed |

A single-turn microphone diagnostic isolates model/device function from
subsequent interruption events. A manual Start dialog solved the missed timing
windows; it opens the microphone only after an explicit Start click. That run
passed automatic checks and the operator confirmed clear/complete playback.
Its two ASR calls took 2.898s and 2.867s; VAD stop to speech submission was
5.083s, followed by 0.368s to first TTS PCM. The reported 25.082s from listening
window opening to first output includes the operator's wait before speaking;
it is not a model-response latency. The latency remains unacceptable to the
operator and is the next active performance issue.
Live diagnostics use
explicit course preactivation with job actions disabled; they do not qualify
ownership or natural duplex behavior. No microphone recordings or user
transcripts are retained. The installed multipart spool threshold is 1MiB,
above the enforced 600,000-byte request limit; uploads remain in memory.

The generated-input pipeline took 32.356s in one run, including about 22.477s
between committed transcript and speech submission. Separate real Qwen requests
took 26.182s and 0.233s to first text. The cause of that variable provider wait
is unverified. Slow samples are retained; none establishes the proposed 1s
acoustic response target. No acoustic p95 or scored benchmark is claimed.

Reproduction, pins, test logs and a synthetic voice sample are in
[November 7 D2 evidence](evidence/2026-11-07/d2/README.md).
D2's model/service and controlled single-turn headphone portions pass. Natural
duplex interaction and performance remain unqualified. The operator requested
the current upstream course benchmark to quantify the remaining gaps.
Normal voice mode still requires D3 wake and real speaker/overlap/addressee
verification. Cached backchannels, uncertainty handling, word-level playback
accounting, long dictation, real website/browser checks, dataset scoring,
acoustic targets and Raspberry Pi qualification remain open.

## November 6: D1 model access and runtime lifetime gate passed

After the operator completed Pi sign-in, real inference succeeded with both
explicit selections: foreground `Qwen/Qwen3.8-27B` and worker
`openai-codex/gpt-6.1-sol`. No credentials, account settings, billing or models
were changed by verification.

- **Real foreground: 2/2 checks passed again.** Marker and arithmetic responses
  matched. First text arrived in 0.185469 s and 0.088029 s; full request times
  were 0.295845 s and 0.119244 s. The production adapter verified the exact
  response model, requested thinking disabled, and observed no reasoning or
  tool-call deltas.
- **Real Pi inference: passed.** `ME3_D1_PI_OK` returned in 4.600206 s after
  settlement. RPC selection matched before and after the request. The saved
  assistant response metadata also reports `openai-codex/gpt-6.1-sol` and normal
  `stop` termination, for both the smoke request and the job below. Worker
  tools/extensions/context discovery remained disabled.
- **Actual runtime with both real models: 9/9 checks passed.** A Pi prompt was
  in flight and its durable job was running while Qwen answered `42` in
  0.249421 s. `AgentRuntime.end_session` left that job running and the same Pi
  process alive. The job completed afterward with `ME3_D1_JOB_OK`; the ended
  session received no completion. Another owner could not retrieve it. The
  original owner reconnected and explicitly retrieved/delivered the result.
  This exercised trusted text sessions and the actual session-ending code;
  no physical voice capture, ASR, TTS or acoustic delivery was used.
- **Fresh installed full suite: 120 passed, 0 failures, 0 skips**, in 4.242 s.

Tested source: `94a0eeb1af36ca1ee0105d770f89bbf25362790d`. Receipts and methods
are in [the authenticated D1 evidence](evidence/2026-11-06/d1/authenticated/README.md).
The earlier authentication failure below is retained. These few text timings
are not p95 measurements or acoustic benchmark qualification. D1 is complete
at the model-access/runtime boundary; the next deliverable is D2, stable real
Mac Whisper/Kokoro inference and speech pipeline qualification. Real website
build/revision/browser verification, ownership, acoustic and Pi hardware gates
remain unpassed.

## November 6: initial D1 check before Pi sign-in

The operator configured foreground `Qwen/Qwen3.8-27B` and selected Pi worker
`openai-codex/gpt-6.1-sol`. These are explicit operator selections, not model
fallbacks. The foreground endpoint and credentials remain in the ignored `.env`.

- **Real foreground provider: 2/2 checks passed.** The exact marker and arithmetic
  requests returned `ME3_D1_FOREGROUND_OK` and `42`. First content arrived in
  0.181676 s and 0.080826 s; complete streamed requests took 0.291573 s and
  0.113699 s. The production adapter verified the exact response model ID,
  requested thinking disabled, and observed no reasoning or tool-call deltas.
  These are two text samples, not p95 or acoustic benchmark measurements.
- **Real controller with Qwen: 2/2 checks passed.** The actual runtime/controller
  delivered `ACK`, then recalled `amber falcon` on the second turn. Turn totals
  were 0.214655 s and 0.138173 s. Delivery was a text callback; no ASR, TTS,
  microphone or acoustic playback was exercised.
- **Pi provider inference: blocked, not passed.** Local RPC verified the exact
  selected provider/model, but the prompt was rejected: `No API key found for
  openai-codex.` The isolated Pi auth file has no entry for that provider and no
  worker API-key forwarding is configured. The supported next step is operator
  sign-in through `./scripts/me3.sh pi` and `/login`; no account, billing or model
  setting was changed. No successful worker inference or real website job is
  claimed.
- **Fresh installed full suite: 120 passed, 0 failures, 0 skips**, in 5.357 s.
  This is regression evidence, separate from the provider checks above.

Source tested: `2d8b7d25aa0f13d5a0feb16bdf1a380cb8fb551b`. Sanitized receipts
and the full suite log are in [evidence/2026-11-06/d1](evidence/2026-11-06/d1).
At this point D1 remained partial pending a real authenticated Pi request; the
later check above resolves that blocker. The separate Mac speech stalls and
ownership/acoustic/hardware gates below remain unpassed.

## November 4 implementation baseline

The active branch is `feat/pi-full-duplex-v1`, descended from prototype
`642cc73`. Pi.dev is the default worker; the controller remains harness-neutral.
This report supersedes the older verification notes preserved below.

## Implemented

1. Distinct worker/foreground configuration, explicit exact model selection,
   dependency-isolated runtime and long-lived job ownership independent of voice.
2. Bounded rolling ASR snapshots, timestamped revisions/stable prefixes/commits,
   cancellable streamed clauses, cross-session/epoch audio tokens, output fencing,
   and ordered whole-clause transport receipts. Provisional pause retains PCM.
3. Wake candidates, deliberate enrollment, session-local reference erasure,
   strict owner/addressee/overlap evidence, inactivity revocation, SmartTurn
   readiness and inference-independent local mute/stop controls.
4. Persistent per-job Pi RPC sessions, exact model/provider verification before
   prompting, settlement/error checks, tool-disabled generation and host-owned
   scoped static website builds with real Node syntax checks and hash receipts.
5. Durable owner-filtered/idempotent jobs; revisions/cancellation/results; grouped
   deferred notices; explicit focus and return; read-only revision-bound loopback
   previews; no model-returned command execution or automatic public deployment.
6. Setup/launch/diagnostic commands, isolated Mac speech service, optional AEC3
   playback-reference front end, declared benchmark profiles and recorded probes.

All implementation stages have code and regression coverage. **Full specification
acceptance is not complete.** The HTTP speaker-verifier adapter is an integration
boundary, not a bundled/qualified identity, overlap or addressee engine. Cached
outgoing Kokoro backchannels, calibrated uncertain-entity confirmation,
word-aligned heard-prefix accounting, long-dictation
stitching, licensed Krisp behavior, live-provider website/browser behavior and
all acoustic/target-hardware gates remain open.

## Test progression and independent review

| Stage | Full local suite | Evidence |
| --- | --- | --- |
| Configuration/runtime | 68 tests; 67 passed, 1 absent-Pipecat skip | stage1-suite.txt |
| Incremental/playback | 75 passed, 0 skips | stage2-suite.txt |
| Ownership/turns | 83 passed, 0 skips | stage3-suite.txt |
| Pi/static websites | 90 passed, 0 skips | stage4-suite.txt |
| Results/context | 98 passed, 0 skips | stage5-suite.txt |
| Final integration | **120 passed, 0 failures, 0 skips** | stage6-suite.txt |

Every stage has preceding RED evidence. The final independent reviewer found
five material issues: idle ownership expiry, speech suppression with running
focus, preview reconnect lifetime, silent provider failures and repeated-request
deduplication. Regressions reproduced each; fixes also cover late enrollment
across mute and bounded speech-service admission, including native calls still running after
HTTP cancellation. Further regressions fence
cross-session playback tokens, failed-probe readiness, ASR snapshot overflow,
completed-job queue capacity and duplicate active revisions.
Model output containing host-command text is verified inert.

An intermediate 114-test run failed the existing legacy console's unchanged
three-second process-start timeout during host slowdown. That failure is retained
in `stage6-contention-failure.txt`; a subsequent quiet run passed 114/114 without
relaxing its timeout. The final receipt includes later regressions and formatting.
Global Python initially had MCP 2.x, incompatible with the declared MCP <2;
that failed run is retained. Current tests use the installed isolated MCP 1.30.0.

## Actual local measurements, separate from simulations

- Installed Pi 0.84.2 accepted RPC and reported exactly
  `openai-codex/gpt-5.6-sol`. No provider prompt was used for this check. The
  isolated auth directory has not been signed in; account entitlement/inference
  remains unverified. Installed provider documentation supports ChatGPT
  subscription sign-in and explicitly selected API-key providers.
- Pipecat source `6f777a0...` installed and its API smoke ran. The scheduling
  regression runs actual Pipecat processors with fixture inference/in-process
  transport; it proves receipt ordering, not acoustic delivery.
- macOS enumerated 7 audio devices (5 with input, 5 with output capability).
  A one-second simultaneous native input/output smoke captured 15,360 input
  frames and played 24,000 silence frames; zero callback status errors. Input
  samples were immediately discarded; no microphone recording was saved.
- Real bundled SmartTurn ONNX synthetic-silence smoke completed in approximately
  0.365 s in the initial probe. Its COMPLETE output on that artificial clip is
  not a behavioral score; readiness still requires usable committed ASR.
- Actual WebRTC AEC3/reference-adapter smoke processed 50 synthetic 20ms frames
  in approximately 0.399 s including adapter/import overhead. No physical echo
  reduction, voice preservation, double-talk or acoustic stop latency was measured.
- MLX speech dependencies installed separately: Python 3.12.13, mlx-whisper
  0.4.3, mlx-audio 0.6.4 and Misaki 0.9.4. Misaki rejects Python 3.13; that
  concrete installation blocker and its Python-3.12 resolution are recorded.
- Exact Whisper large-v3-turbo weights were downloaded, preserving the cached
  smaller Whisper models. Kokoro uses the cached requested bf16 model. A real
  synthetic roundtrip stalled before the first Kokoro PCM and was stopped;
  separate exact-model Whisper inference exceeded a hard 45-second bound and
  was terminated. **Neither is passed.** There is no valid live speech latency
  or successful MLX roundtrip result. See mlx-roundtrip.json and whisper-probe.txt.
- Simulator benchmark: 20 trials per idle/busy-worker track, with artificial
  model delays and request-to-text clocks. Its metrics/source hashes are in
  simulation-final/metrics.json (and the earlier simulation/ receipt). These timings are explicitly not acoustic/model
  latency and cannot establish the <=250ms or <=1s proposed p95 targets.

## Benchmark and deployment

The external benchmark was fetched at
`106ac8e543a5fd996e254a87e69fa101bfd27a42`. Its launcher/rate check returned READY
for 16kHz input/24kHz output. The scorer was not edited; all score-module hashes
and clean external Git state are recorded in benchmark-scorer.json. No dataset,
judge or scored acoustic run was executed. Course ownership bypass is global;
end-to-end ownership must be evaluated separately, with wake/verification enabled.

No Raspberry Pi was attached or qualified. No 30-minute soak, controlled
idle/busy M2 contention qualification, accents/replay ownership dataset or physical
speakerphone test was run. Mac software/device smoke cannot qualify the Pi4.
The standalone course rubric and second Markdown attachment were not available;
the attached November 4 spec and the user's six stage names were used.

## November 4 unpassed acceptance gates (historical; see updates above)

**Stable real Mac speech inference and pipeline qualification.** Resolve the
recorded Kokoro/Whisper stalls, choose the speech service token in `.env`, and
run the actual end-to-end headphone pipeline. Independently, supply the exact
foreground endpoint/model/API settings and authenticate Pi, then verify real
foreground/Pi inference and a built/revised website. Live owner mode additionally
requires a real authenticated speaker/overlap/addressee verifier service.
Do not turn missing credentials or these unpassed implementations/tests into
simulation successes. Setup/launch commands and remaining boundaries are in
[SETUP.md](SETUP.md). Evidence lives under `docs/evidence/2026-11-04/`.

---

# Historical prototype verification

# Duplex prototype verification — 2026-11-02

## Observed in this implementation session

The new overlay test suite ran on Linux/Python 3.13. Three initial test batches
first failed because their implementation modules did not exist. After
implementation, a self-review identified a pending-ASR race. Two regression tests
reproduced it: VAD silence could release a notice or an older response before the
new transcript arrived. Both passed after separating acoustic silence from
finalized-turn permission.

The final new suite has **31 tests: 30 pass, 1 explicit skip**. The skipped test
requires real Pipecat imports. Tests cover lexical policy, pending-ASR/floor races,
independent jobs, stale response fencing, deferred/retried notices, errors, bounded
subprocess output, cancellation/reaping, timeout, Pi settled-event handling, and
explicit provider configuration. Subprocesses are fixture programs, not Hermes/Pi.

`python -m me3.duplex_demo` ran successfully and asserted five control invariants.
It is an in-memory simulation. Compile checks passed for the new source, tests
and benchmark entry. New Python source lines are at most 79 characters; no
external style checker was available. No independent reviewer agent was available;
the review was performed in the implementation session.

## Not verified

- The old repository's full test suite was not rerun locally: the environment
  could read GitHub through the connector but could not clone/install through
  shell networking. The overlay preserves the old Supervisor unchanged.
- Pipecat was not installed; pipeline execution, provider behavior and actual
  playback receipts were not run. The API smoke test is honestly skipped.
- Real Hermes/Pi startup and inference, live microphone/speaker, MLX/Kokoro
  compatibility, AEC, M2/Pi4 throughput and network contention remain unmeasured.
- No Full-Duplex-Bench dataset was executed or scored. There are no acoustic
  latency results, no human acceptance result, and no speech-to-speech parity claim.
- The formal ME3 rubric and full other-chat transcript were not retrieved. Prior
  requirements came from the committed project documentation and this request.

## Publication and review scope

The new branch builds on `perliminary` at `6a044dba...`; it does not rewrite main,
rename old branches, replace the old SQLite supervisor or modify the benchmark.
The source pins are inspected compatibility targets, not a transitive dependency
lock. A source-compatible build still needs an installed-runtime smoke test.

First qualification: install the exact sources and actual providers; run the
full repository tests; run the optional Pipecat smoke; test microphone with
headphones; test interruption flushing and transport receipts; then run one
course-benchmark round with recordings and failure denominators. Replace per-call
process startup and buffered ASR/LLM only after preserving this regression suite.

## Post-publication CI and pipe-cleanup correction

GitHub Actions run `41455864296`, job `125312236109`, tested the complete
repository on Ubuntu/Python 3.12.15: **60 tests, 59 passed, 1 skipped**. The
existing SQLite/persistence suite and actual MCP SDK smoke passed, as did the
legacy demo, simulator benchmark and compile checks. Pipecat remained absent.

Although CI concluded success, its logs exposed an unclosed stdout transport
after the output-limit test. A new regression reproduced the issue locally:
the child had exited but stdout had not reached EOF. Teardown now closes stdin
and drains unread stdout concurrently with process termination, then waits for
both output pipes instead of cancelling the stderr reader prematurely.

After this correction, the local new suite reports **32 tests, 31 passed,
1 skipped**, with ResourceWarning reporting enabled and no cleanup warning in
the captured log. The deterministic demo and compilation also passed. This
supersedes the local counts above. The initial CI receipt applies to commit
`2629613`; the correction requires its own subsequent CI receipt. Neither run
provides live audio, real Hermes/Pi inference or acoustic benchmark evidence.
