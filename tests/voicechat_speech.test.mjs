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

test("only freshness forces the lookup; Pi judges ordinary questions and handles requests", async () => {
  const {publicFactCheck} = await import("../integrations/voicechat/speech.mjs");
  assert.equal(publicFactCheck("What is the capital of France?"), false);
  assert.equal(publicFactCheck("Can you draft a checklist for the latest release?"), false);
  assert.equal(publicFactCheck("Draft the latest release notes."), false);
  assert.ok(publicFactCheck("What is the latest stable release of Blender?"));
  assert.equal(publicFactCheck("Who won the championship?"), false);
  assert.equal(publicFactCheck("Write a website about a bridge."), false);
  assert.equal(publicFactCheck("Who is Mira Sol?", "We were discussing a music player."), false);
  assert.equal(publicFactCheck("Why do leaves change color?", "The draft is ready."), false);
  assert.equal(publicFactCheck("Who is Mira Sol?", "Mira Sol leads our design team."), false);
  assert.equal(publicFactCheck("What color was the folder?", "The folder was green."), false);
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

test("a recheck can speak a sourced paraphrase and a rejected query leaves room for local context", async () => {
  const {checkSearchReply,searchFallback} = await import("../integrations/voicechat/speech.mjs");
  const reply = "Repairs finished in October and the bridge reopened.";
  assert.equal(checkSearchReply(reply,"The bridge reopened in October after repairs."),reply);
  assert.equal(searchFallback({lookupRejected:true,searchAttempted:true}),undefined);
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

test("search speech keeps a sourced lead even when it exceeds the tool word budget", async () => {
  const {spokenToolReply} = await import("../integrations/voicechat/speech.mjs");
  const lead = "The North Pier ferry will resume weekday service in October after the port finishes repairing the boarding ramp that was damaged during the spring storms, according to the harbor authority, which says that the weekend timetable will remain unchanged until the winter schedule is published later this year.";
  assert.equal(spokenToolReply(`${lead} More detail follows.`, {search:true}), lead);
  assert.doesNotMatch(spokenToolReply(lead), /full response is in Pi/i);
});

test("search speech gives the findings, not a handoff, and leaves sources on screen", async () => {
  const {spokenToolReply} = await import("../integrations/voicechat/speech.mjs");
  const answer = "The full response is in Pi. **The bridge reopened**, per [the port](https://example.com/bridge). [1] Repairs finished on Friday. More background follows.\n\nSources:\n- [Port bulletin](https://example.com/bridge)";
  assert.equal(spokenToolReply(answer, {search:true}), "The bridge reopened, per the port. Repairs finished on Friday.");
  assert.equal(spokenToolReply("Sources:\n- [Port bulletin](https://example.com/bridge)", {search:true}),
    "I couldn’t summarize what I found this time.");
  assert.equal(spokenToolReply("I couldn’t verify the reopening.", {search:true}), "I couldn’t verify the reopening.");
  assert.equal(spokenToolReply("", {search:true}), "");
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
