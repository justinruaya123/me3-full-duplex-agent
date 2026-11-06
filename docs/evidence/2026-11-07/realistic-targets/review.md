# Independent source review

Reviewed source frozen at **`6bbbfd5`**: the provisional-backchannel paths in
`me3/duplex.py`, `me3/incremental.py`, `me3/capture.py` and
`me3/audio_pipeline.py`, their focused regressions, and the selected Whisper
inference change. This review found two concrete floor-control defects, then
re-read their fixes. **No Important or Critical finding remained in that source
snapshot.** This is a source/control review, not physical audio qualification.

- **Actual PCM boundary.** `TTSStartedFrame` can precede the first TTS PCM.
  The original playback predicate could therefore consume an acknowledgment
  during synthesis startup. It now also requires `received > 0`. I identified
  the reachable path from source and read the actual Pipecat slow-first-PCM
  regression and RED/GREEN receipts. The guard establishes transport-observed
  PCM, not audibility at a speaker.
- **Current-question lifetime.** I reproduced the prior defect with the real
  controller and fixture backend/speech: while “Would you like the details?”
  was being delivered, `pending_question` was still false; provisional “yes”
  became a backchannel and its later committed revision became stale. The fix
  sets an epoch-owned question guard before awaiting speech and checks it in
  both provisional and committed classification. Interrupt clears it; delayed
  cleanup only clears the matching epoch. I read regressions for delivery,
  later semantic commitment and cancellation-resistant old-question cleanup.
- **Provisional speech grants no request authority.** The ended-capture flag
  remains separate from semantic commitment. The floor-only branch does not
  call request acceptance, spawn foreground inference, append user history,
  change focus/epoch or execute/cancel jobs. The finite English acknowledgment
  matcher supplies lexical evidence only. Pending/current questions, uncertain
  addressing, missing playback or lost delivery rights keep the turn held.
- **All-hypothesis veto.** Rolling capture latches any non-acknowledgment
  hypothesis before ownership ingress can drop it. The controller also latches
  what it observes. A later acknowledgment or false metadata cannot erase that
  evidence. This conservatively controls floor relaxation; it does not approve
  an action or override ownership/SmartTurn for a nonempty commit.
- **Generation and lifetime fences.** Capture consumption checks generation,
  session, turn, revision, ended state and acknowledgment provenance. New
  speech, invalidation, mute and close fence late results. It preserves only
  post-capture preroll and retires the consumed generation. I found no normal
  pipeline suspension between the successful floor decision and synchronous
  capture consumption: the capture lock retains its revision, and verifier
  return checks generation. Rejected consumption does not resume PCM.

I read the prior root receipts for **208/208 installed tests** and the
**178/178 v1 subset**, zero failures/errors/skips, plus the focused
**26/26** receipt containing **five actual Pipecat scheduling/transport
fixtures**, and **45/45** related control tests. The focused review RED had
26 tests and four failures. I did not rerun those suites or run new inference
during this re-review. ASR, SmartTurn, foreground, TTS and worker outputs in the
five pipeline fixtures are test inputs. The final benchmark score and subsequent
final-suite receipts are owned by the coordinating agent and are not certified
by this note.

For ASR I read the installed `detect_language` feature-input contract, exact
decoder-mel construction, complete-byte cache keys and restoration paths, plus
the [20-pair report](asr/encoder-policy-quality.json). All measured pairs retain
text, language and every word field. Excluding only the initial ordinary cold
pair leaves 17 warm ordinary pairs at 1.823815s versus 0.977800s; two ambiguous
pairs remain separate. The confidence >=0.95 path changes language-detection
padding. Its probability is not a calibrated correctness guarantee, and neither
same weights nor these development pairs prove universal language/quality parity.

I executed the private TTS compiler probes. The state-capture attempt stopped
because the installed API lacks public RNG state. The explicitly authorized
public-canary revision stopped after seven speech generations when its first
warm compiled call changed observed PRNG continuation. Strict numerical output
also differed. The decoder was restored; the candidate was rejected. The
remaining texts, changed-seed pair and full coverage phase were not reached and
are not counted as passes. No compiler or dtype change was promoted.

I also read the foreground pilot's rejection note and the parent's recorded
full-answer quality decision. Literal guards and shorter first clauses did not
prevent an incorrect causal explanation or resolve missing referents. I did not
rerun that provider pilot or independently certify all its outputs. Its prompt
candidate was not promoted. No latency result in these development probes
establishes semantic correctness, a learned prosodic classifier, licensed SDK
parity, physical speakerphone/AEC, ownership accuracy or Raspberry Pi acceptance.
