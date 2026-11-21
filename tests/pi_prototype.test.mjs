import assert from "node:assert/strict";
import test from "node:test";
import { registerPrototype, prototypeRequest, loadRenderer } from "../me3/pi_prototype.mjs";

function harness() {
  const listeners = {}, notices = [], saves = [], tools = {};
  let turn = { id: "turn-1", text: "Please prototype a study planner." };
  registerPrototype({
    registerTool(tool) { tools[tool.name] = tool; },
    on(event, fn) { listeners[event] = fn; },
  }, {
    getTurn: () => turn,
    message: text => notices.push(text),
    ask: async (op, text) => { saves.push({op, text}); return "Saved"; },
  });
  return {
    listeners, notices, saves, tool: tools.me3_prototype, setTurn: value => { turn = value; },
    async delta(html, id = "call-1") {
      const partial = { content: [{ type: "toolCall", name: "me3_prototype", id, arguments: { html } }] };
      await listeners.message_update({ assistantMessageEvent: { type: "toolcall_delta", contentIndex: 0, partial } });
    },
  };
}

test("a current explicit request authorizes prototyping", () => {
  for (const text of ["Prototype a timer", "Please build me a prototype of a page", "Could you mock up a tracker?", "Build a prototype of a poll"]) {
    assert.equal(prototypeRequest(text), true, text);
  }
  for (const text of ["What is a prototype?", "Read note.txt about my prototype", "Don't prototype a timer", "Explain this file: prototype a calculator", ""]) {
    assert.equal(prototypeRequest(text), false, text);
  }
});

test("the upstream partial renderer retains finished styles and native controls", async () => {
  const render = await loadRenderer();
  const html = render("<style>.card{color:red}</style><body><details open><summary>More</summary></details><p cla");
  assert.match(html, /<style>.card\{color:red\}<\/style>/);
  assert.match(html, /<details open=""/);
  assert.doesNotMatch(html, /<p cla/);
});

test("the standalone artifact has restrictive CSP and only local presentation elements", async () => {
  const render = await loadRenderer();
  const html = render('<meta http-equiv="refresh" content="0;url=https://outside.test"><a href="https://outside.test" ping="/x">Go</a><iframe src="https://outside.test"></iframe><input type="file"><input type="checkbox"><script>boom()</script><p onclick="boom()">Hello</p>');
  assert.match(html, /default-src 'none'/);
  assert.match(html, /<input type="checkbox">/);
  assert.match(html, /Hello/);
  assert.doesNotMatch(html, /outside\.test|<iframe|<script|onclick|type="file"|ping=/);
});

test("serves changing preview before tool completion, saves once and closes for session shutdown", async t => {
  const h = harness();
  t.after(() => h.listeners.session_shutdown());
  await h.delta("<body><h1>Revision one</h1>");
  const url = h.notices.join(" ").match(/http:\/\/127\.0\.0\.1:\d+\/[\w-]+\//)[0];
  const state = async () => (await fetch(url + "state")).json();
  const first = await state();
  assert.match(first.html, /Revision one/);
  assert.equal(first.done, false);
  assert.equal(h.saves.length, 0);
  assert.equal((await fetch(new URL("/", url))).status, 404);
  assert.equal((await fetch(url, {method:"POST"})).status, 405);
  const shell = await (await fetch(url)).text();
  assert.match(shell, /<iframe sandbox/);
  await h.delta("<h1>Revision two</h1>");
  assert.match((await state()).html, /Revision two/);
  const result = await h.tool.execute("call-1", {html:"<details><summary>Final</summary>Details</details>"});
  assert.match(result.content[0].text, /\.html/);
  assert.match(h.saves[0].text, /^prototype-[\w-]+\.html = <!doctype html>/i);
  assert.equal(h.saves[0].op, "save");
  assert.equal((await state()).done, true);
  await h.listeners.agent_end();
  assert.match((await state()).html, /Final/);
  await h.listeners.session_shutdown();
  await assert.rejects(fetch(url));
});

test("rejects incidental mentions, stale calls, oversized output and aborted work", async t => {
  const h = harness();
  t.after(() => h.listeners.session_shutdown());
  await h.delta("<h1>old</h1>");
  h.setTurn({id:"new", text:"Prototype a clock"});
  await assert.rejects(h.tool.execute("call-1", {html:"<h1>wrong turn</h1>"}));
  h.setTurn({id:"question", text:"Explain prototype inheritance"});
  await h.delta("oops", "call-2");
  await assert.rejects(h.tool.execute("call-2", {html:"oops"}));
  h.setTurn({id:"last", text:"Prototype a clock"});
  await assert.rejects(h.tool.execute("call-3", {html:"X".repeat(17000)}));
  await assert.rejects(h.tool.execute("call-4", {html:"<h1>Late</h1>"}, AbortSignal.abort()));
  assert.deepEqual(h.saves, []);
});

test("rechecks committed voice authorization before publishing and before saving", async t => {
  const h = harness();
  t.after(() => h.listeners.session_shutdown());
  let current = false;
  h.setTurn({id:"voice", text:"Prototype a planner", isCurrent:async () => current});
  await h.delta("<p>Pending</p>");
  assert.deepEqual(h.notices, []);
  await assert.rejects(h.tool.execute("call-1", {html:"<p>Late</p>"}), /expired/);
  await h.listeners.agent_end();

  current = true;
  h.setTurn({id:"next-voice", text:"Prototype a calendar", isCurrent:async () => current});
  await h.delta("<p>November</p>", "call-2");
  assert.equal(h.notices.length, 1);
  current = false;
  await assert.rejects(h.tool.execute("call-2", {html:"<p>November</p>"}), /expired/);
  assert.deepEqual(h.saves, []);
});

test("late tool execution cannot adopt a new turn after the previous stream was cancelled", async t => {
  const h = harness();
  t.after(() => h.listeners.session_shutdown());
  await h.delta("<p>First request</p>");
  await h.listeners.agent_end();
  h.setTurn({id:"new", text:"Prototype a different page"});
  await assert.rejects(h.tool.execute("call-1", {html:"<p>First request</p>"}), /expired/);
  assert.deepEqual(h.saves, []);
});
