import test from "node:test";
import assert from "node:assert/strict";
import {WindowVoice, expression} from "../integrations/voicechat/face.mjs";

test("a wake phrase in a current partial lights the face and revisions replace the caption", () => {
  const v = new WindowVoice("hey beemo");
  v.audio({kind:"ready"});
  v.audio({kind:"onset", id:"a"});
  v.audio({kind:"partial", id:"old", text:"Hey Beemo"});
  assert.equal(expression(v.state), "idle");
  v.audio({kind:"partial", id:"a", text:"Hey, BMO"});
  assert.equal(expression(v.state), "listening");
  v.audio({kind:"final", id:"a", text:"Hey, BMO, write a note."});
  v.audio({kind:"commit", id:"a"});
  assert.equal(v.state.asr, "Hey, BMO, write a note.");
  assert.equal(expression(v.state, true), "thinking");
});

test("speaking follows playback, pauses on overlap and resumes only an interrupted output", () => {
  const v = new WindowVoice();
  v.audio({kind:"ready"});
  v.audio({kind:"playing"});
  assert.equal(expression(v.state, true), "speaking");
  v.audio({kind:"paused"});
  v.audio({kind:"onset", id:"u"}, true);
  assert.equal(expression(v.state, true), "listening");
  v.audio({kind:"discard", id:"u"});
  assert.equal(expression(v.state, true), "speaking");
  v.audio({kind:"interrupted"});
  assert.equal(expression(v.state, true), "thinking");
  assert.equal(expression(v.state), "idle");
});

test("one visual tool call presents the browser only once across streamed HTML and the final page", async () => {
  const {mkdtemp, readFile, rm, unlink} = await import("node:fs/promises");
  const {tmpdir} = await import("node:os");
  const {join} = await import("node:path");
  const {registerVisual} = await import("../integrations/voicechat/visual.mjs");
  const dir = await mkdtemp(join(tmpdir(),"me3-face-"));
  const previous = process.env.ME3_WINDOW_DIR;
  process.env.ME3_WINDOW_DIR = dir;
  const events = new Map(), tools = new Map();
  try {
    registerVisual({on:(n,f)=>events.set(n,f), registerTool:t=>tools.set(t.name,t)}, () => "turn", undefined, async () => html => html);
    await events.get("session_start")();
    const content = {html:"<h1>Afternoon</h1>"};
    const call = {id:"one-dashboard", name:"show_visual", arguments:content};
    events.get("message_update")({assistantMessageEvent:{type:"toolcall_delta",toolCall:call}});
    assert.deepEqual(JSON.parse(await readFile(join(dir,"focus.json"))), {panel:"canvas",request:call.id});
    await unlink(join(dir,"focus.json"));
    await tools.get(call.name).execute(call.id, content, new AbortController().signal);
    assert.equal(JSON.parse(await readFile(join(dir,"canvas.json"))).html,content.html);
    await assert.rejects(readFile(join(dir,"focus.json")), {code:"ENOENT"});
  } finally {
    events.get("session_shutdown")?.();
    if (previous === undefined) delete process.env.ME3_WINDOW_DIR;
    else process.env.ME3_WINDOW_DIR = previous;
    await rm(dir,{recursive:true,force:true});
  }
});

test("a delayed playback start after interruption cannot revive the speaking face", () => {
  const v = new WindowVoice();
  v.audio({kind:"playing",receipt:"old"});
  v.audio({kind:"interrupted"});
  v.audio({kind:"playing",receipt:"old"});
  assert.equal(expression(v.state),"idle");
  v.audio({kind:"playing",receipt:"new"});
  v.audio({kind:"played",receipt:"old"});
  assert.equal(expression(v.state),"speaking");
});
