import {test} from "node:test";
import assert from "node:assert/strict";
import {registerVisual} from "../integrations/voicechat/visual.mjs";

test("one voice-steered view streams drafts, rejects old turns and restores the last finished page", async () => {
  const events = new Map(), phases = [];
  let tool, turn = "one";
  const pi = {on:(name, handler) => events.set(name, handler), registerTool:t => {tool=t;}};
  registerVisual(pi, () => turn, data=>phases.push([data.html,data.done]), async ()=>html=>html);
  const ctx = {};
  await events.get("session_start")({},ctx);
  const delta = (id,html) => events.get("message_update")({assistantMessageEvent:{
    type:"toolcall_delta",contentIndex:0,partial:{content:[{id,type:"toolCall",name:tool.name,arguments:{html}}]}}},ctx);
  await delta("a","<h1>Area");
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.deepEqual(phases.at(-1),["<h1>Area",false]);
  const result = await tool.execute("a",{html:"<h1>Area</h1>"},new AbortController().signal,()=>{},ctx);
  assert.ok(!result.content[0].text.includes("<h1>"));
  turn="two";
  await delta("b","Draft change");
  turn="three";
  await assert.rejects(tool.execute("b",{html:"Stale"},new AbortController().signal,()=>{},ctx));
  events.get("agent_settled")();
  assert.deepEqual(phases.at(-1),["<h1>Area</h1>",true]);
  await delta("c","Second step");
  await tool.execute("c",{html:"Second step"},new AbortController().signal,()=>{},ctx);
  assert.deepEqual(phases.at(-1),["Second step",true]);
  events.get("session_shutdown")();
});

test("the local renderer displays a delimited equation as native math and preserves safe controls", async () => {
  const {loadRenderer} = await import("../integrations/voicechat/preview.mjs");
  const render = await loadRenderer();
  const page = render(String.raw`<p>First step: \[2x=8\]</p><input type="range"><script>bad()</script>`);
  assert.match(page, /<math /);
  assert.match(page, /type="range"/);
  assert.doesNotMatch(page, /bad\(\)/);
});

test("model styles and hidden controls cannot override the host's readable theme", async () => {
  const {loadRenderer} = await import("../integrations/voicechat/preview.mjs");
  const render = await loadRenderer();
  const page = render('<style>p{display:none}</style><p style="position:fixed" hidden>Keep this result readable</p>');
  assert.match(page, /Keep this result readable/);
  assert.doesNotMatch(page, /display:none|position:fixed|<p hidden/);
});

test("a citation retains its web address in the read-only visual", async () => {
  const {loadRenderer} = await import("../integrations/voicechat/preview.mjs");
  const render = await loadRenderer();
  const html = render('<p><a href="https://example.org/minutes">Meeting minutes</a></p>');
  assert.match(html, /Meeting minutes/);
  assert.match(html, /https:\/\/example\.org\/minutes/);
  assert.doesNotMatch(html, /<a\s/i);
});
