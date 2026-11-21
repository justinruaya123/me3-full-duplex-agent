import {test} from "node:test";
import assert from "node:assert/strict";
import {TurnGate} from "../integrations/voicechat/turn-gate.mjs";

test("desktop input needs an affirmative answer for the same live request", async () => {
  const {approveDesktopInput} = await import("../integrations/voicechat/approval.mjs");
  let current = true;
  const actions = [{action:"press",ref:"@e2"}];
  assert.equal(await approveDesktopInput(actions, () => current, async () => true), true);
  assert.equal(await approveDesktopInput(actions, () => current, async () => false), false);
  assert.equal(await approveDesktopInput(actions, () => current, async () => { current=false; return true; }), false);
  assert.equal(await approveDesktopInput(actions, () => current, () => assert.fail("expired turn")), false);
});

test("only a local commitment matching the active mic item and final enters Pi", () => {
  const gate = new TurnGate();
  gate.onset("a");
  assert.equal(gate.commit("a", "build"), false);
  gate.final("a", "build");
  gate.onset("b");
  assert.equal(gate.commit("a","build"), false);
  gate.final("b","build");
  assert.equal(gate.commit("b","different"), false);
  assert.equal(gate.commit("b","build"), true);
  assert.equal(gate.commit("b","build"), false);
  gate.onset("c");
  gate.final("c","");
  assert.equal(gate.commit("c",""), false);
});

test("only an explicit answer begun after the spoken approval prompt can approve it", async () => {
  const {SpokenApproval} = await import("../integrations/voicechat/approval.mjs");
  const a = new SpokenApproval();
  const result = a.ask("q", new AbortController().signal);
  a.onset("early");
  a.played("q");
  assert.equal(a.answer("early","yes"), "unheard");
  a.onset("later");
  assert.equal(a.answer("later","yes, go ahead"), "approved");
  assert.equal(await result, true);
  const denied = a.ask("next", new AbortController().signal);
  a.played("q");
  a.onset("stale"); assert.equal(a.answer("stale","yes"), "unheard");
  a.played("next");
  a.onset("new"); assert.equal(a.answer("new","yes, but change the title"), "unclear");
  assert.equal(await denied, false);
  const desktop = a.ask("desktop", new AbortController().signal, "act_ui");
  a.played("desktop"); a.onset("reply");
  assert.equal(a.answer("reply", "Build it."), "unclear");
  assert.equal(await desktop, false);
});

test("natural spoken preferences and aborts resolve only their own question", async () => {
  const {SpokenApproval} = await import("../integrations/voicechat/approval.mjs");
  const a = new SpokenApproval();
  for (const [utterance, expected] of [
    ["I'd rather build it.", "approved"], ["Yes, please go ahead.", "approved"],
    ["No, don’t build it.", "declined"], ["I’d rather skip it.", "declined"],
    ["Yes, if you change the title.", "unclear"], ["Mm-hm.", "unclear"]
  ]) {
    const result = a.ask("q", new AbortController().signal);
    a.played("q"); a.onset("answer");
    assert.equal(a.answer("answer", utterance), expected);
    assert.equal(await result, expected === "approved");
  }
  const abort = new AbortController();
  const aborted = a.ask("old", abort.signal);
  abort.abort();
  assert.equal(await aborted, false);
  assert.equal(a.answer("old", "yes"), undefined);
});
