import test from "node:test";
import assert from "node:assert/strict";

test("a played ordinary question and a statement both admit a listener; approval protects the floor", async () => {
  const {listenerMode} = await import("../integrations/voicechat/behavior.mjs");
  assert.deepEqual(listenerMode(false, false), {op:"listener", enabled:true, awaiting_answer:false});
  assert.deepEqual(listenerMode(true, false), {op:"listener", enabled:true, awaiting_answer:true});
  assert.deepEqual(listenerMode(false, true), {op:"listener", enabled:false, awaiting_answer:true});
});

test("a session cycles each purpose independently", async () => {
  const {cuePicker, phrases} = await import("../integrations/voicechat/behavior.mjs");
  const pick = cuePicker();
  const first = pick("wake");
  assert.ok(phrases.accepted.includes(pick("accepted")));
  assert.notEqual(pick("wake"), first);
  assert.equal(new Set(Array.from({length:phrases.wake.length}, () => pick("wake"))).size, phrases.wake.length);
});

test("slow voice turns get one cue and a bounded stall; progress or a superseding turn fences timers", async t => {
  const {VoiceWait} = await import("../integrations/voicechat/behavior.mjs");
  t.mock.timers.enable({apis:["setTimeout"]});
  const events = [], waiting = new VoiceWait(id => events.push(["cue",id]), id => events.push(["stall",id]));
  waiting.start("fast");
  waiting.end("fast");
  waiting.start("old");
  waiting.start("current");
  waiting.end("old");
  t.mock.timers.tick(2600);
  assert.deepEqual(events,[["cue","current"]]);
  waiting.tool("current","lookup",true);
  t.mock.timers.tick(30000);
  assert.equal(events.length,1);
  waiting.tool("current","lookup",false);
  t.mock.timers.tick(15000);
  waiting.progress("current");
  t.mock.timers.tick(12000);
  assert.equal(events.length,1);
  t.mock.timers.tick(15000);
  assert.deepEqual(events.at(-1),["stall","current"]);
});

test("a truncated or failed voice turn explains the failure; interruptions stay quiet", async () => {
  const {voiceFailure} = await import("../integrations/voicechat/behavior.mjs");
  assert.ok(voiceFailure("length"));
  assert.ok(voiceFailure("error"));
  assert.equal(voiceFailure("aborted"), "");
  assert.equal(voiceFailure("stop"), "");
});

test("a listening sound cannot satisfy a delegated task acknowledgment", async () => {
  const {finishVoiceText} = await import("../integrations/voicechat/behavior.mjs");
  assert.equal(finishVoiceText("[acknowledged]", {jobCue:"On it."}), "");
  assert.match(finishVoiceText("[acknowledged]", {listenerCue:"Mm-hm."}), /result/);
  assert.equal(finishVoiceText("Here is the draft.", {jobCue:"On it."}), "Here is the draft.");
});

test("search and waiting cues use speakable words, and tool dispatch silences the generic timer", async t => {
  const {VoiceWait, phrases} = await import("../integrations/voicechat/behavior.mjs");
  assert.doesNotMatch(Object.values(phrases).flat().join(" "), /\b[hm]+[- ]+[hm]+\b/i);
  assert.deepEqual(phrases.searching, ["Searching."]);
  assert.ok(phrases.waiting.length);
  t.mock.timers.enable({apis:["setTimeout"]});
  const cues = [], wait = new VoiceWait(id => cues.push(id), () => {});
  wait.start("a");
  wait.tool("a","search",true);
  t.mock.timers.tick(4000);
  assert.deepEqual(cues, []);
  wait.end("a");
});
