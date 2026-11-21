// Brave evidence lives only in this Pi session. Closing the database drops it.
import {randomUUID} from "node:crypto";
import {DatabaseSync} from "node:sqlite";

const normalized = text => text.normalize("NFC").toLowerCase().trim().replace(/\s+/g, " ").replace(/[?!]+$/, "");
const localDay = date => [date.getFullYear(), date.getMonth() + 1, date.getDate()]
  .map(n => String(n).padStart(2, "0")).join("-");

export function openSearchStore() {
  const db = new DatabaseSync(":memory:");
  db.exec(`PRAGMA temp_store=MEMORY;
    CREATE TABLE receipts(id TEXT UNIQUE, key TEXT, query TEXT, retrieved INTEGER, day TEXT, evidence TEXT);
    CREATE INDEX find_receipt ON receipts(key, retrieved);`);
  const newest = db.prepare("SELECT evidence FROM receipts WHERE key=? AND retrieved BETWEEN ? AND ? ORDER BY retrieved DESC,rowid DESC LIMIT 1");
  const history = db.prepare("SELECT query, evidence FROM receipts WHERE (? IS NULL OR day=?) ORDER BY retrieved DESC,rowid DESC");
  const byId = db.prepare("SELECT evidence FROM receipts WHERE id=?");
  return {
    get(key, now) {
      const row = newest.get(key, +now - 15 * 60_000, +now);
      return row && JSON.parse(row.evidence);
    },
    save(key, query, evidence) {
      const id = randomUUID();
      const date = new Date(evidence.retrieved_at);
      const entry = {...evidence, id, query, retrieved_local_date:localDay(date)};
      db.prepare("INSERT INTO receipts VALUES(?, ?, ?, ?, ?, ?)").run(
        id, key, normalized(query), +date, entry.retrieved_local_date, JSON.stringify(entry));
      db.exec("DELETE FROM receipts WHERE rowid <= (SELECT rowid FROM receipts ORDER BY rowid DESC LIMIT 1 OFFSET 128)");
      return entry;
    },
    recall(terms, day) {
      const tokenize = text => new Set(normalized(text).match(/[\p{L}\p{N}]+/gu) || []);
      const words = [...tokenize(terms)];
      const matches = [];
      for (const row of history.iterate(day ?? null, day ?? null)) {
        const entry = JSON.parse(row.evidence);
        const question = tokenize(row.query);
        const evidence = tokenize(entry.support);
        // A different requested year or figure must not drift to a nearby topic.
        if (words.some(w => /^\d+$/.test(w) && !question.has(w) && !evidence.has(w))) continue;
        const direct = words.filter(w => question.has(w)).length;
        const supported = words.filter(w => !question.has(w) && evidence.has(w)).length;
        if (direct + supported < Math.ceil(words.length * 0.65)) continue;
        matches.push({entry, score:2 * direct + supported});
      }
      return matches.sort((a,b) => b.score - a.score).slice(0,4).map(m => m.entry);
    },
    byId(id) {
      const row = byId.get(id);
      return row && JSON.parse(row.evidence);
    },
    close() {db.close();}
  };
}

export async function runSearch(store, plan, fetch, {now = new Date(), refresh = false} = {}) {
  const key = JSON.stringify([normalized(plan.query), plan.mode, plan.freshness]);
  if (!refresh && !plan.force_live && plan.mode !== "news" && !["pd","pw","pm","py"].includes(plan.freshness)) {
    const saved = store.get(key, now);
    if (saved) return {...saved, origin:"session"};
  }
  const evidence = await fetch(plan);
  if (evidence.error || !evidence.urls?.length) return evidence;
  return {...store.save(key, plan.query, evidence), origin:"live"};
}

// Pi can persist tool messages. Persist only opaque references and operation metadata.
export function searchReceipt(entries, origin) {
  const details = {origin, search_refs:entries.map(e => e.id), source_count:entries.reduce((n,e) => n + e.urls.length, 0),
    retrieved_at:entries[0]?.retrieved_at, mode:entries[0]?.mode};
  const text = entries.length ? `Brave · ${origin} · ${details.source_count} sources · retrieved ${details.retrieved_at}` :
    "No matching Brave lookup in this session.";
  return {content:[{type:"text", text}], details};
}

export function withSearchEvidence(message, store) {
  const refs = message.details?.search_refs;
  if (!refs?.length) return message;
  const entries = refs.map(id => store.byId(id)).filter(Boolean);
  if (!entries.length) return {...message, content:[{type:"text",text:"The search evidence expired with its session."}]};
  return {...message, details:{...entries[0], ...message.details},
    content:[{type:"text",text:JSON.stringify({origin:message.details.origin, display:message.details.display, results:entries.map(e => ({
      ref:e.id, query:e.query, excerpts:e.brief, sources:e.sources, source_dates:e.source_dates, retrieved_at:e.retrieved_at, retrieved_local_date:e.retrieved_local_date}))})}]};
}

// The current exchange and the two preceding exchanges on this Pi branch.
export function recentSearchContext(messages, store) {
  let start = 0, users = 0;
  for (let j = messages.length - 1; j >= 0; j--) {
    if (messages[j].role === "user" && ++users === 3) {start = j; break;}
  }
  const receipts = new Map();
  let hydrated = messages;
  for (let j = start; j < messages.length; j++) {
    const m = messages[j];
    if (m.role !== "toolResult" || m.isError || !m.details?.search_refs?.length) continue;
    if (hydrated === messages) hydrated = messages.slice();
    hydrated[j] = withSearchEvidence(m,store);
    for (const id of m.details.search_refs) {
      const entry = store.byId(id);
      if (entry) receipts.set(id,entry);
    }
  }
  return {messages:hydrated, receipts};
}

export function resultsBoard(evidence) {
  return {title:"Brave search results", rows:evidence.items.slice(0,5).map(hit => ({
    kind:"note", label:hit.title.slice(0,80), detail:hit.snippet.slice(0,140), href:hit.url,
  }))};
}
