import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openChatMemory } from "../integrations/voicechat/memory.mjs";

test("a fresh saved chat recalls the previous chat in the same private profile", t => {
  const dir = mkdtempSync(join(tmpdir(), "me3-chat-memory-"));
  t.after(() => rmSync(dir, {recursive:true, force:true}));
  const settings = {profile:dir, sessionFile:"saved.jsonl"};
  const first = openChatMemory(settings);
  first.record("one", "turn", "The rehearsal is called Marigold.");
  first.reply("one", "turn", "We chose Friday.");
  first.close();
  const next = openChatMemory(settings);
  try {
    assert.match(next.recall("two","When is the rehearsal?"), /Marigold.*Friday/s);
    assert.equal(next.recall("one","rehearsal"), "");
    assert.equal(statSync(join(dir, "conversation.sqlite3")).mode & 0o777, 0o600);
    assert.equal(openChatMemory({...settings, enabled:"0"}), undefined);
    assert.equal(openChatMemory({...settings, fixture:true}), undefined);
    assert.equal(openChatMemory({...settings, sessionFile:undefined}), undefined);
    assert.throws(() => openChatMemory({...settings, enabled:"maybe"}), /0 or 1/);
    const other = openChatMemory({...settings, profile:join(dir,"other")});
    assert.equal(other.recall("two","rehearsal"), "");
    other.close();
  } finally { next.close(); }
});

test("an expressly remembered detail survives history rotation and reaches a fresh voice prompt", async t => {
  const {composeVoicePrompt, composeWorkerPrompt} = await import("../integrations/voicechat/prompts.mjs");
  const profile = mkdtempSync(join(tmpdir(), "me3-personal-"));
  t.after(() => rmSync(profile, {recursive:true, force:true}));
  const store = openChatMemory({profile,sessionFile:"first"});
  try {
    const asked = "Can you remember this? I prefer a short agenda.";
    store.record("one","1",asked);
    store.remember("one","1","I prefer a short agenda.");
    store.remember("one","1","I prefer a short agenda.");
    assert.throws(() => store.remember("one","1","Invented detail"));
    assert.throws(() => store.remember("two","1","I prefer a short agenda."));
    for (let i=0; i<260; i++) store.record("one",String(i+2),"An unrelated exchange.");
  } finally {store.close();}
  const prompt = await composeVoicePrompt("voice", profile);
  assert.equal(prompt.split("I prefer a short agenda.").length, 2);
  assert.doesNotMatch(await composeVoicePrompt("voice", profile, {includeRemembered:false}), /I prefer a short agenda/);
  assert.doesNotMatch(await composeWorkerPrompt(profile), /I prefer a short agenda/);
});

test("direct requests are distinguished from recall questions and quoted text", async () => {
  const {directMemoryDetail} = await import("../integrations/voicechat/memory.mjs");
  assert.equal(directMemoryDetail("Can you remember this? I prefer a short agenda."), "I prefer a short agenda.");
  assert.equal(directMemoryDetail("Please remember that my project is called Orchid."), "my project is called Orchid.");
  for (const text of ["Can you remember what I said?", "Don't remember that I like pears.",
      "She said, 'Remember that I like pears.'", "Remember that?", "Can you remember this?"])
    assert.equal(directMemoryDetail(text), undefined);
});

test("remember that can refer to the speaker's previous turn within this chat", t => {
  const profile = mkdtempSync(join(tmpdir(), "me3-reference-"));
  t.after(() => rmSync(profile, {recursive:true, force:true}));
  const store = openChatMemory({profile,sessionFile:"voice.jsonl"});
  try {
    store.record("one","a","I prefer short agendas.");
    store.record("other","b","A different user's words.");
    store.record("one","c","Please remember that.");
    assert.throws(() => store.remember("one","c","A different user's words."));
    assert.equal(store.remember("one","c","I prefer short agendas."),"I prefer short agendas.");
    store.record("one","d","Don't save this. I prefer long agendas.");
    assert.throws(() => store.remember("one","d","I prefer long agendas."));
  } finally {store.close();}
});

test("losing the thread brings back adjacent turns of the most recent conversation", t => {
  const dir = mkdtempSync(join(tmpdir(), "me3-thread-"));
  t.after(() => rmSync(dir, {recursive:true, force:true}));
  const store = openChatMemory({profile:dir,sessionFile:"some-session"});
  try {
    store.record("project","1","We picked the blue cover.",100);
    store.record("unrelated","2","I lost my train of thought about lunch.",110);
    store.record("project","3","Only the subtitle is left.",120);
    const query = "I lost my train of thought. Where were we?";
    assert.deepEqual(JSON.parse(store.recall("fresh",query)).map(row => row.user),
      ["We picked the blue cover.","Only the subtitle is left."]);
  } finally {store.close();}
});

test("a full profile rejects a save without losing existing entries", async t => {
  const {writeFileSync,readFileSync} = await import("node:fs");
  const profile = mkdtempSync(join(tmpdir(), "me3-full-profile-"));
  t.after(() => rmSync(profile, {recursive:true, force:true}));
  const path = join(profile,"USER.md");
  const original = "a".repeat(8180);
  writeFileSync(path,original,{mode:0o600});
  const store = openChatMemory({profile,sessionFile:"voice.jsonl"});
  try {
    store.record("one","a","Remember that I like a short agenda.");
    assert.throws(() => store.remember("one","a","I like a short agenda."), /full/);
    assert.equal(readFileSync(path,"utf8"), original);
  } finally {store.close();}
});

test("the current thread wins over a matching older chat until the user asks for it", t => {
  const dir = mkdtempSync(join(tmpdir(),"me3-recent-"));
  t.after(() => rmSync(dir,{recursive:true,force:true}));
  const store = openChatMemory({profile:dir,sessionFile:"saved"});
  try {
    store.record("old","one","The harbor schedule was delayed.");
    for (const query of ["Tell me more about that.", "What about the harbor schedule?","Where were we?"])
      assert.equal(store.recall("now",query,{activeThread:true}),"");
    assert.equal(store.recall("fresh","What's a nebula?"),"");
    assert.match(store.recall("now","From our previous chat, what was the harbor schedule?",{activeThread:true}),/was delayed/);
  } finally {store.close();}
});
