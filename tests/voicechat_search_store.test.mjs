import test from "node:test";
import assert from "node:assert/strict";
import { openSearchStore, runSearch } from "../integrations/voicechat/search-store.mjs";

const plan = {query:"Who won the 2022 Philippine presidential election?", mode:"answers", freshness:null};
const sample = {provider:"Brave", mode:"web", brief:"A reported result.", urls:["https://example.org/report"],
  source_dates:[{url:"https://example.org/report", published_at:"2022-05-26", reported_age:null}],
  support:"Source evidence.", sources:"Original report", subject:plan.query};

test("only a completed provider request seeds the session and repeats retain its original dates", async () => {
  const db = openSearchStore(), calls = [];
  let now = new Date("2026-11-20T23:00:00Z");
  const fetch = async p => { calls.push(p); return {...sample, retrieved_at:now.toISOString()}; };
  try {
    const first = await runSearch(db, plan, fetch, {now});
    now = new Date(+now + 60_000);
    const repeat = await runSearch(db, {...plan, query:plan.query.toUpperCase()}, fetch, {now});
    assert.equal(first.origin, "live");
    assert.equal(repeat.origin, "session");
    assert.equal(repeat.retrieved_at, first.retrieved_at);
    assert.equal(repeat.source_dates[0].published_at, "2022-05-26");
    assert.equal(calls.length, 1);
    const refreshed = await runSearch(db, plan, fetch, {now, refresh:true});
    assert.equal(refreshed.origin, "live");
    assert.equal(calls.length, 2);
    assert.equal(db.recall("Philippine election", first.retrieved_local_date).length, 2);
    assert.equal(db.recall("Philippine election", "2022-05-26").length, 0);
  } finally {db.close();}
});

test("freshness, requested windows, independent sessions and failed refreshes stay separate", async () => {
  const db = openSearchStore(), other = openSearchStore();
  const now = new Date(), live = async () => ({...sample, retrieved_at:now.toISOString()});
  try {
    await runSearch(db, plan, live, {now});
    assert.equal(other.recall("Philippine", null).length, 0);
    for (const p of [{...plan, mode:"news", freshness:"pd"}, {...plan, freshness:"2022-05-01to2022-05-31"}]) {
      assert.equal((await runSearch(db, p, live, {now})).origin, "live");
    }
    assert.equal((await runSearch(db, {...plan, mode:"news", freshness:"pd"}, live, {now})).origin, "live");
    const fail = async () => ({error:"Brave unavailable"});
    assert.deepEqual(await runSearch(db, plan, fail, {now, refresh:true}), {error:"Brave unavailable"});
    assert.deepEqual(await runSearch(db, plan, fail, {now:new Date(+now + 86400001)}), {error:"Brave unavailable"});
    assert.equal(db.recall("Philippine", null).length, 4);
  } finally {db.close(); other.close();}
});

test("dated recall accepts query and evidence vocabulary while respecting years and retrieval dates", async () => {
  const store = openSearchStore(), now = new Date("2026-11-20T23:22:00Z");
  try {
    const entry = await runSearch(store, plan, async () => ({...sample, support:"The winning candidate was Santos.",
      retrieved_at:now.toISOString()}), {now});
    assert.equal(store.recall("2022 Philippine presidential election winner Santos",entry.retrieved_local_date).length,1);
    assert.equal(store.recall("2024 Philippine election",entry.retrieved_local_date).length,0);
    assert.equal(store.recall("medical library",entry.retrieved_local_date).length,0);
  } finally {store.close();}
});

test("ordinary Pi history holds only a receipt; evidence expires on closing the session", async () => {
  const {searchReceipt,withSearchEvidence} = await import("../integrations/voicechat/search-store.mjs");
  const first = openSearchStore(), next = openSearchStore(), now = new Date();
  try {
    const entry = await runSearch(first, plan, async () => ({...sample,retrieved_at:now.toISOString()}));
    const message = searchReceipt([entry], "live");
    assert.ok(!JSON.stringify(message).includes("example.org"));
    assert.ok(withSearchEvidence(message,first).content[0].text.includes("example.org"));
    assert.match(withSearchEvidence(message,next).content[0].text,/expired/);
  } finally {first.close(); next.close();}
});

test("a follow-up can select source evidence across a conversational turn on its branch", async () => {
  const {recentSearchContext, searchReceipt} = await import("../integrations/voicechat/search-store.mjs");
  const store = openSearchStore(), other = openSearchStore();
  try {
    const entry = await runSearch(store, plan, async () => ({...sample, retrieved_at:new Date().toISOString()}));
    const user = {role:"user"}, answer = {role:"assistant", stopReason:"stop"};
    const receipt = {role:"toolResult", toolName:"web_lookup", ...searchReceipt([entry],"live")};
    const chain = [user, receipt, answer, user, answer, user];
    const ctx = recentSearchContext(chain,store);
    assert.equal(ctx.receipts.get(entry.id).query, plan.query);
    assert.equal(JSON.parse(ctx.messages[1].content[0].text).results[0].ref,entry.id);
    assert.equal(recentSearchContext([...chain, answer, user],store).receipts.size,0);
    assert.equal(recentSearchContext(chain,other).receipts.size,0);
    assert.equal(recentSearchContext([user,answer,user],store).receipts.size,0);
  } finally {store.close(); other.close();}
});

test("search results use the titles, excerpts and links from the receipt", async () => {
  const {resultsBoard} = await import("../integrations/voicechat/search-store.mjs");
  const {validBoard} = await import("../integrations/voicechat/theme/display.mjs");
  const hit = {title:"A public guide", snippet:"The sourced excerpt.", url:"https://example.org/guide"};
  const board = resultsBoard({items:[hit]});
  assert.equal(board.rows[0].href,hit.url);
  assert.equal(board.rows[0].label,hit.title);
  assert.equal(board.rows[0].detail,hit.snippet);
  assert.ok(validBoard(board));
  assert.equal(validBoard({...board,rows:[{...board.rows[0],href:"javascript:alert(0)"}]}),false);
});
