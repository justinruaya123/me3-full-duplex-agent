import test from "node:test";
import assert from "node:assert/strict";
import {researchRequest, chosenFacts, verifiedFacts} from "../integrations/voicechat/portfolio.mjs";

test("research needs both a site and an explicit public self-lookup", () => {
  for (const text of ["Make me a portfolio website and look up my work", "Research me online and build a site about me",
                      "Search more about me and build a portfolio website on the canvas"])
    assert.ok(researchRequest(text));
  for (const text of ["Make me a portfolio website", "Don't look up my work for my website", "Research a website about trees"])
    assert.equal(researchRequest(text), false);
});
test("only an explicit, in-range choice approves exactly the presented facts", () => {
  const facts = [{text:"One"},{text:"Two"},{text:"Three"}];
  assert.deepEqual(chosenFacts("Use the first and third.", facts), [0,2]);
  assert.deepEqual(chosenFacts("Approve all.", facts), [0,1,2]);
  for (const text of ["yes","use 4","use 1 and skip 2","don't use all","use the secret profile"])
    assert.equal(chosenFacts(text, facts), undefined);
});
test("facts need a matching source URL and evidence in a real Brave result", () => {
  const rows = [{url:"https://example.org/art",snippet:"Ada exhibited in June.",title:"Show"}];
  const fact = {text:"Ada exhibited in June.",url:rows[0].url,quote:rows[0].snippet};
  assert.deepEqual(verifiedFacts([fact,{...fact,url:"https://elsewhere.org"}], rows), [{text:fact.text,url:fact.url}]);
  assert.deepEqual(verifiedFacts([{...fact,quote:"Made up evidence."}], rows), []);
});

test("a name from the private profile needs a separate search confirmation", async () => {
  const {mkdtemp,writeFile,rm} = await import("node:fs/promises");
  const {tmpdir} = await import("node:os");
  const {join} = await import("node:path");
  const {searchName} = await import("../integrations/voicechat/portfolio.mjs");
  const dir = await mkdtemp(join(tmpdir(),"portfolio-profile-"));
  try {
    const profile = join(dir,"USER.md");
    await writeFile(profile,"- Full name, if useful: Private Owner\n");
    assert.deepEqual(await searchName(dir),{name:"Private Owner",approved:false});
    await writeFile(profile,"- Public search name: Public Handle\n- Full name, if useful: Private Owner\n");
    assert.deepEqual(await searchName(dir),{name:"Public Handle",approved:true});
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test("a spoken selection may name facts using distinctive words", () => {
  const facts = [{text:"Created a calculus reviewer."},{text:"Was interviewed about a computer."},{text:"Featured in the same newspaper."}];
  assert.deepEqual(chosenFacts("Use the reviewer and interview.", facts), [0,1]);
  assert.deepEqual(chosenFacts("Include only the calculus reviewer.", facts), [0]);
  assert.equal(chosenFacts("Use the reviewer and invent a job.", facts), undefined);
  assert.equal(chosenFacts("Use the computer.", [...facts,{text:"Built a computer."}]), undefined);
});

test("interrupting a review releases the turn while the research can finish", async () => {
  const {waitForResearch} = await import("../integrations/voicechat/portfolio.mjs");
  const worker = Promise.withResolvers(), mic = new AbortController();
  const review = waitForResearch(worker.promise,mic.signal);
  mic.abort();
  await assert.rejects(review,/interrupted/);
  worker.resolve("completed research");
  assert.equal(await waitForResearch(worker.promise,new AbortController().signal),"completed research");
});

test("an operator without a profile can supply a search name by voice", async t => {
  const {mkdtemp, rm} = await import("node:fs/promises");
  const {tmpdir} = await import("node:os");
  const {join} = await import("node:path");
  const {newPortfolioReview, spokenSearchName} = await import("../integrations/voicechat/portfolio.mjs");
  const dir = await mkdtemp(join(tmpdir(), "bmo-name-"));
  t.after(() => rm(dir,{recursive:true,force:true}));
  assert.match((await newPortfolioReview(dir,true)).nameQuestion, /search for/i);
  assert.equal(spokenSearchName("Search for Ada Lovelace."), "Ada Lovelace");
  assert.equal(spokenSearchName("My name is José Vega."), "José Vega");
  assert.equal(spokenSearchName("What's the weather?"), undefined);
});

test("Pi retries an empty review from its existing Brave receipt before returning facts", async () => {
  const {reviewPortfolioFacts} = await import("../integrations/voicechat/portfolio.mjs");
  const row = {url:"https://example.org/art",title:"The June show",snippet:"Ada exhibited in June."};
  const fact = {text:row.snippet,quote:row.snippet,url:row.url};
  let retries = 0;
  const session = {
    state:{messages:[{role:"assistant",stopReason:"stop"}]},
    getLastAssistantText:() => retries ? JSON.stringify([fact]) : "",
    async prompt() { retries++; },
    async waitForIdle() {},
  };
  assert.deepEqual(await reviewPortfolioFacts(session,[row]), [{text:row.snippet,url:row.url}]);
  assert.equal(retries,1);
  session.getLastAssistantText = () => "unfinished JSON";
  assert.deepEqual(await reviewPortfolioFacts(session,[row]), []);
  assert.equal(retries,2);
});
