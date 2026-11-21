import test from "node:test";
import assert from "node:assert/strict";
import {spokenReply} from "../integrations/voicechat/speech.mjs";

test("a scoped freshness correction requires fresh evidence before speaking", async () => {
  const {recheckRequest, searchFallback} = await import("../integrations/voicechat/speech.mjs");
  for (const input of ["Think there's some more modern there.", "Is there anything newer?",
    "Yes, but you're not using web search.", "Give me a web search."]) {
    assert.ok(recheckRequest(input), input);
  }
  for (const input of ["Don't search that again.", "Find a more modern sofa.", "New topic: search for Mars."])
    assert.equal(recheckRequest(input), false, input);
  assert.ok(searchFallback({requiresSearch:true}));
  assert.ok(searchFallback({lookup:Promise.resolve()}));
  assert.equal(searchFallback({requiresSearch:true, liveEvidence:true}), undefined);
  assert.equal(searchFallback({}), undefined);
});

test("BMO initiates verification for dates and changing facts without an explicit search command", async () => {
  const {publicFactCheck} = await import("../integrations/voicechat/speech.mjs");
  assert.ok(publicFactCheck("So who... When did Sri Lanka got the bad, overthrowing of government?"));
  assert.ok(publicFactCheck("What is the latest stable release of Blender?"));
  assert.ok(publicFactCheck("Who won the championship?"));
  assert.equal(publicFactCheck("Write a website about a bridge."), false);
});

test("speak the label and takeaway, leave link destinations, citations and styling in Pi", () => {
  assert.equal(spokenReply("**The deadline is Friday**, per [the registrar](https://example.org/date). [1]\n\nSources:\n- https://example.org/date"), "The deadline is Friday, per the registrar.");
});
test("preserve names, versions, negative numbers and spoken arithmetic", () => {
  assert.equal(spokenReply("1. Use `Python 3.14.2`.\n2. **2** * 3 is 6, and -0.5 is negative."), "Use Python 3.14.2. 2 times 3 is 6, and -0.5 is negative.");
});
test("code blocks are visual, an emphasized follow-up still sounds like a question", () => {
  assert.equal(spokenReply("~~~js\nconst answer = 2 * 3;\n~~~\n_Want the next step?_"), "Want the next step?");
});

test("search summaries cannot introduce exact figures absent from cited content", async () => {
  const {checkSearchReply} = await import("../integrations/voicechat/speech.mjs");
  const evidence = "The scout counted 12 birds in 2025.";
  assert.equal(checkSearchReply("There were 12 birds.", evidence), "There were 12 birds.");
  assert.equal(checkSearchReply("The scout counted 12 birds. Another observer saw 20.", evidence),
    "The scout counted 12 birds.");
  assert.match(checkSearchReply("There were 12.5 birds.", evidence), /couldn’t verify/i);
  assert.match(checkSearchReply("The release was 3.15.2.", "The latest release is on the download page."), /couldn’t verify/i);
});

test("the pass after a lookup can answer from evidence without issuing the same search again", async () => {
  const {afterLookup} = await import("../integrations/voicechat/speech.mjs");
  const other = {type:"function",function:{name:"show_visual"}};
  const request = {tools:[{type:"function",function:{name:"web_lookup"}},other],model:"test"};
  assert.deepEqual(afterLookup(request),{model:"test",tools:[other]});
  assert.equal(request.tools.length,2);
});

test("a fresh challenge cannot turn an older report into a claim that nothing happened later", async () => {
  const {checkedRecheck} = await import("../integrations/voicechat/speech.mjs");
  const excerpt = "The bridge reopened in October after repairs.";
  assert.equal(checkedRecheck(excerpt, excerpt), excerpt);
  for (const claim of ["No further closures occurred.", excerpt + " There were no later closures.",
    "You probably mean the other bridge.", "The bridge reopened"]) {
    assert.match(checkedRecheck(claim, excerpt), /couldn’t confirm/i);
  }
});

test("read simple TeX, preserve prices, leave advanced notation on screen", () => {
  assert.equal(spokenReply(String.raw`**Result:** $x^2 = \frac{1}{2}$.`),
    "Result: x squared equals 1 over 2.");
  assert.equal(spokenReply("It costs $1, plus shipping."), "It costs 1 dollar, plus shipping.");
  assert.equal(spokenReply("Prices went from $5 to $10.50."), "Prices went from 5 dollars to 10.50 dollars.");
  assert.equal(spokenReply(String.raw`See \[\int_{0}^{1} f(x)\,dx\] for the derivation.`),
    "See the formula in Pi for the derivation.");
});

test("long tool summaries stop on a sentence boundary, normal conversation can continue", async () => {
  const {spokenToolReply} = await import("../integrations/voicechat/speech.mjs");
  const text="Python 3.14.2 is available. **The Linux build is delayed.** More background follows. Here are previous versions.";
  assert.equal(spokenToolReply(text),"Python 3.14.2 is available. The Linux build is delayed.");
  assert.ok(spokenReply(text).endsWith("Here are previous versions."));
});

test("a background notice speaks only a completed draft's labeled takeaway", async () => {
  const {jobNotice} = await import("../integrations/voicechat/speech.mjs");
  const job = {kind:"draft",status:"completed",text:"**Takeaway:** Keep **Thursday** for the review.\n\n## Full agenda\n- More details"};
  assert.equal(jobNotice(job),"Your draft is ready. Keep Thursday for the review.");
  assert.equal(jobNotice({...job,status:"failed"}),"Your draft couldn't be finished.");
  assert.equal(jobNotice({...job,text:"Dear committee,\n\nHere is our proposal."}),"Your draft is ready.");
  assert.equal(jobNotice({...job,kind:"website"}),"Your website is ready.");
});

test("a public subject follows only its own completed turn on the current chat branch", async () => {
  const {previousSearchReceipt} = await import("../integrations/voicechat/speech.mjs");
  const user = {role:"user", content:"a question"};
  const receipt = {role:"toolResult", toolName:"web_lookup", details:{subject:"public election result"}};
  const answer = {role:"assistant", stopReason:"stop"};
  assert.equal(previousSearchReceipt([user,receipt,answer,user])?.subject, "public election result");
  assert.equal(previousSearchReceipt([user,receipt,answer,user,answer,user]), undefined);
  assert.equal(previousSearchReceipt([user,receipt,{...answer,stopReason:"aborted"},user]), undefined);
});
