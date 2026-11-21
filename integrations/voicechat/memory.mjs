import { constants, closeSync, fchmodSync, fstatSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const stopWords = new Set("a an and are about did do for from have how i in is it me my of on or our that the this to we what with you your previous last chat session remember recall discuss".split(" "));
const terms = text => new Set((text.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => !stopWords.has(t)));

// Only unambiguous, self-contained requests take the no-tool fast path.
const saveLead = /^(?:(?:can|could|would|will) you (?:please )?|please )?(?:remember|keep in mind|make a note of|save to (?:my |your )?memory)\b/i;
const saveTail = /(?:[.!?,]\s*|\s+)(?:please )?(?:remember (?:that|this)|keep (?:that|this) in mind|save (?:that|this) (?:to|in) (?:my |your )?memory)[.!]?$/i;
const referenceOnly = /^(?:(?:can|could|would|will) you (?:please )?|please )?(?:remember (?:that|this)|keep (?:that|this) in mind|save (?:that|this) (?:to|in) (?:my |your )?memory)[.!?]*$/i;

function allowsSave(text) {
  if (/\b(?:don['’]t|do not|never)\s+(?:want you to\s+)?(?:save|remember|store|keep)\b/i.test(text)) return false;
  return (saveLead.test(text) && !/\bremember\s+(?:what|who|when|where|why|how|whether|if)\b/i.test(text))
    || saveTail.test(text) || referenceOnly.test(text)
    || /^(?:for future (?:chats|conversations)|from now on|I(?:['’]d like| want) you to remember)\b/i.test(text);
}

export function directMemoryDetail(text) {
  text = text.trim();
  if (!allowsSave(text)) return;
  let detail;
  if (saveLead.test(text)) {
    detail = text.replace(saveLead,"").replace(/^\s*(?:this[?!.:,]\s*|that\s+|[:,-]\s*)/i,"").trim();
  } else if (saveTail.test(text)) {
    detail = text.replace(saveTail, "").trim();
  }
  if (detail && /^(?:I\b|I['’]|my\s)/i.test(detail) && detail.length <= 300 &&
      !/[?;\n]|[.!]\s+\S|\band (?:then |please )?(?:tell|show|search|draft|send|remind)\b/i.test(detail)) return detail;
}

export function openChatMemory({profile, sessionFile, enabled = "1", fixture = false}) {
  if (!["0", "1"].includes(enabled)) throw Error("ME3_MEMORY_ENABLED must be 0 or 1");
  if (enabled === "0" || fixture || !sessionFile) return;
  mkdirSync(profile, {recursive:true, mode:0o700});
  const path = join(profile, "conversation.sqlite3");
  const fd = openSync(path, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
  try { fchmodSync(fd, 0o600); } finally { closeSync(fd); }

  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(path);
  try {
    db.exec(`
      PRAGMA busy_timeout=250;
      CREATE TABLE IF NOT EXISTS exchanges (
        session TEXT NOT NULL, turn TEXT NOT NULL, asked TEXT NOT NULL, answered TEXT,
        created INTEGER NOT NULL, UNIQUE(session, turn)
      );
      CREATE TRIGGER IF NOT EXISTS limit_exchanges AFTER INSERT ON exchanges BEGIN
        DELETE FROM exchanges WHERE rowid < (
          SELECT rowid FROM exchanges ORDER BY rowid DESC LIMIT 1 OFFSET 255
        );
      END;`);
    const insert = db.prepare("INSERT OR IGNORE INTO exchanges(session, turn, asked, created) VALUES (?,?,?,?)");
    const answer = db.prepare("UPDATE exchanges SET answered=? WHERE session=? AND turn=? AND answered IS NULL");
    const past = db.prepare("SELECT session, asked, answered, created FROM exchanges WHERE session != ? ORDER BY created DESC, rowid DESC");
    return {
      record(session, turn, text, created = Date.now()) {
        if (text.trim()) insert.run(session, turn, text.trim().slice(0, 1000), created);
      },
      remember(session, turn, detail) {
        if (typeof detail !== "string" || !detail.trim() || detail.length > 300 ||
            /[\x00-\x1f\x7f<>]/.test(detail)) throw Error("Use one short, verbatim detail.");
        detail = detail.trim();
        // Serialize concurrent Pi sessions using the existing profile database lock.
        db.exec("BEGIN IMMEDIATE");
        let fd;
        try {
          const source = db.prepare("SELECT rowid, asked FROM exchanges WHERE session=? AND turn=?").get(session,turn);
          if (!source || !allowsSave(source.asked)) throw Error("The current turn does not request a saved detail.");
          const previous = referenceOnly.test(source.asked) && db.prepare(
            "SELECT asked FROM exchanges WHERE session=? AND rowid<? ORDER BY rowid DESC LIMIT 1"
          ).get(session, source.rowid);
          if (!(previous?.asked || source.asked).includes(detail)) throw Error("The detail must quote the user.");
          const path = join(profile,"USER.md");
          fd = openSync(path, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
          const info = fstatSync(fd);
          if (!info.isFile() || info.size > 8192) throw Error("Private USER.md is unavailable or full.");
          const existing = readFileSync(fd,"utf8");
          const entry = "- " + detail;
          if (!existing.split(/\r?\n/).includes(entry)) {
            const heading = "## Remembered details";
            const prefix = existing.includes("\n" + heading + "\n") ? "\n" : "\n\n" + heading + "\n";
            const add = prefix + "<!-- ME3 remembered -->\n" + entry + "\n<!-- /ME3 remembered -->\n";
            if (info.size + Buffer.byteLength(add) > 8192) throw Error("Private USER.md is full.");
            const staged = join(profile, ".remember-" + randomUUID());
            try {
              writeFileSync(staged, existing + add, {mode:0o600, flag:"wx", flush:true});
              renameSync(staged, path);
            } finally { rmSync(staged,{force:true}); }
          }
          db.exec("COMMIT");
          return detail;
        } catch (error) {
          db.exec("ROLLBACK");
          throw error;
        } finally {
          if (fd !== undefined) closeSync(fd);
        }
      },
      reply(session, turn, text) {
        if (text.trim()) answer.run(text.trim().slice(0, 1000), session, turn);
      },
      recall(session, query) {
        const wanted = terms(query);
        let rows = past.all(session);
        // A request to pick the thread back up needs neighboring turns from one chat.
        const resume = /\b(?:where (?:were we|did we leave off)|(?:lost|losing) my train of thought|pick up where we left off)\b/i.test(query);
        if (resume) rows = rows.filter(row => row.session === rows[0]?.session).slice(0, 3);
        const ranked = rows.map(row => {
          const words = terms(row.asked + " " + (row.answered || ""));
          const score = [...wanted].filter(word => words.has(word)).length;
          return {row, score};
        });
        // Recency breaks ties and supplies context for a generic follow-up.
        const excerpts = [];
        for (const {row} of ranked.sort((a,b) => b.score - a.score).slice(0, 3)) {
          const entry = {date:new Date(row.created).toISOString(), user:row.asked, assistant:row.answered};
          if (JSON.stringify([...excerpts, entry]).length <= 7500) excerpts.push(entry);
        }
        return excerpts.length ? JSON.stringify(excerpts.sort((a,b) => a.date.localeCompare(b.date))) : "";
      },
      close() { db.close(); }
    };
  } catch (error) {
    db.close();
    throw error;
  }
}
