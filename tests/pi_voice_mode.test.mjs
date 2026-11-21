import assert from "node:assert/strict";
import test from "node:test";
import { voiceMode } from "../me3/pi_voice_mode.mjs";

function fixture() {
  const calls = [], labels = [];
  const mode = voiceMode(async (...args) => calls.push(args), text => labels.push(text));
  return {mode, calls, labels};
}

test("interactive launch opens verified voice once and a key pauses and resumes it", async () => {
  const {mode, calls, labels} = fixture();
  await mode.start("tui", "startup");
  await mode.start("tui", "startup");
  assert.deepEqual(calls, [["voice", ""]]);
  mode.observe("voice_open");
  assert.match(labels.at(-1), /verified/i);
  assert.match(labels.at(-1), /\/me3 duplex/);
  await mode.toggle();
  assert.match(labels.at(-1), /\/me3 duplex/);
  await mode.toggle();
  assert.deepEqual(calls.slice(1), [["end"], ["voice", ""]]);
});

test("an explicit demo uses the trusted profile again after pausing", async () => {
  const {mode, calls} = fixture();
  await mode.start("tui", "startup", "demo");
  mode.observe("voice_open");
  await mode.leave("mute");
  mode.observe("voice_closed");
  await mode.start("tui", "reload", "demo");
  assert.deepEqual(calls, [["voice", "demo"], ["mute"]]);
  await mode.toggle();
  assert.deepEqual(calls.at(-1), ["voice", "demo"]);
});

test("headless and text sessions keep the microphone closed unless RPC opts in", async () => {
  for (const [ui, profile] of [["rpc"], ["print","demo"], ["json","demo"], ["tui","off"]]) {
    const {mode, calls} = fixture();
    await mode.start(ui, "startup", profile);
    assert.deepEqual(calls, []);
  }
  const {mode, calls} = fixture();
  await mode.start("rpc", "startup", "demo");
  assert.deepEqual(calls, [["voice", "demo"]]);
});

test("a failed stop leaves a retryable pause and cannot open a second microphone", async () => {
  let stops = 0;
  const calls = [], labels = [];
  const mode = voiceMode(async op => {
    calls.push(op);
    if (op === "end" && !stops++) throw Error("host timeout");
  }, text => labels.push(text));
  await mode.start("tui", "startup");
  mode.observe("voice_open");
  await assert.rejects(mode.toggle(), /timeout/);
  assert.match(labels.at(-1), /unknown/i);
  await mode.toggle();
  assert.deepEqual(calls, ["voice", "end", "end"]);
});

test("full duplex requires output startup and live capture, and reports a stalled mic", async t => {
  t.mock.timers.enable({apis:["setTimeout"]});
  const {mode, labels} = fixture();
  await mode.start("tui", "startup");
  mode.observe("voice_open", "one");
  assert.doesNotMatch(labels.at(-1), /Full duplex/);
  mode.observe("mic_level", "old");
  assert.doesNotMatch(labels.at(-1), /Full duplex/);
  mode.observe("mic_level", "one");
  assert.match(labels.at(-1), /Full duplex/);
  t.mock.timers.tick(3500);
  assert.match(labels.at(-1), /no microphone frames/i);
  mode.observe("mic_level", "one");
  assert.match(labels.at(-1), /Full duplex/);
  mode.observe("voice_closed", "one");
  t.mock.timers.tick(3500);
  assert.match(labels.at(-1), /paused/i);
});
