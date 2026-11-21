import test from "node:test";
import assert from "node:assert/strict";
import { VoiceHandoff } from "../integrations/voicechat/handoff.mjs";

function setup() {
  const sends = [], calls = [];
  const h = new VoiceHandoff(r => { sends.push(r.text); return true; }, (r, c) => calls.push([r.id, c.id]));
  h.start("item1");
  return {h,sends,calls};
}
const text = "Please summarize the local test readme about solar.";
const proposal = {id:"call1",text:"Summarize the local test read me about solar."};

for (const order of ["call first","final first","Pi already running"]) {
  test(order + " binds one call to the original words and one Pi turn", () => {
    const {h,sends,calls} = setup();
    if (order === "call first") h.propose(proposal);
    h.final("item1",text);
    if (order === "Pi already running") h.flush();
    if (order !== "call first") h.propose(proposal);
    h.propose(proposal);
    h.final("item1",text);
    h.flush();
    assert.deepEqual(sends,[text]);
    assert.deepEqual(calls,[["item1","call1"]]);
  });
}

test("unrelated, orphaned and stale calls cannot authorize a handoff", () => {
  const {h,sends,calls} = setup();
  h.propose({id:"old",text:"Do something unrelated"});
  h.start("item2");
  h.final("item1",text);
  h.final("item2","What did we call this project?");
  h.propose(proposal);
  h.flush();
  assert.deepEqual(calls,[]);
  assert.deepEqual(sends,["What did we call this project?"]);
});
test("close clears an unsent final and its timer", async () => {
  const {h,sends} = setup();
  h.final("item1",text);
  h.close();
  await new Promise(resolve=>setTimeout(resolve,180));
  assert.deepEqual(sends,[]);
});

test("native conversation runs Pi only on a grounded delegate, even when late", () => {
  const sent = [];
  const h = new VoiceHandoff(r => { sent.push(r.text); return true; }, () => {}, {delegatesOnly:true});
  h.start("1");
  h.final("1","Hello there");
  h.flush();
  h.start("2");
  h.final("2",text);
  h.flush();
  assert.deepEqual(sent,[]);
  h.propose(proposal);
  h.propose(proposal);
  assert.deepEqual(sent,[text]);
});

test("decoder reconnects are bounded and an operator stop cancels pending recovery", async () => {
  const {VoiceRecovery} = await import("../integrations/voicechat/recovery.mjs");
  const r = new VoiceRecovery();
  let calls = 0;
  assert.ok(r.schedule(() => calls++, 100));
  await new Promise(resolve => setTimeout(resolve,800));
  assert.equal(calls,1);
  assert.ok(r.schedule(() => calls++, 200));
  await new Promise(resolve => setTimeout(resolve,1550));
  assert.equal(calls,2);
  assert.equal(r.schedule(() => calls++,300),false);
  assert.ok(r.schedule(() => calls++,61001));
  r.reset();
  await new Promise(resolve => setTimeout(resolve,800));
  assert.equal(calls,2);
});

test("item-bound call can paraphrase the final and cannot use a different mic item", () => {
  const {h,sends,calls} = setup();
  h.final("item1",text);
  h.propose({...proposal, item:"wrong"});
  assert.deepEqual(calls,[]);
  h.propose({id:"right",item:"item1",text:"Read the file"});
  assert.deepEqual(calls,[["item1","right"]]);
  assert.deepEqual(sends,[text]);
});
