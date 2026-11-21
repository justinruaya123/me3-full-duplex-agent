import {randomUUID} from "node:crypto";
import {execFile} from "node:child_process";
import {mkdtemp, mkdir, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {workerEnv} from "./jobs.mjs";

export function researchRequest(text) {
  return /\b(?:website|portfolio|site|homepage|personal page)\b/i.test(text) &&
    /\b(?:build|create|design|make|prepare|put together)\b/i.test(text) &&
    /\b(?:research|look up|search(?: the web)?(?: for)?(?: more)?|find(?: public)? (?:information|info)(?: about| on)?)\s+(?:about\s+)?(?:me|myself|my (?:public |professional )?(?:work|projects|background))\b/i.test(text) &&
    !/\b(?:never|without|do not|don['’]t|skip|avoid)\b/i.test(text);
}

export function chosenFacts(text, facts) {
  const count = facts.length;
  const answer = text.trim().toLowerCase().replace(/[.!?]+$/, "");
  const pick = /^(?:(?:yes|please)[, ]+)?(?:use|approve|include|publish) (?:only )?(.+)$/.exec(answer)?.[1];
  if (!pick) return;
  if (["both","all three"].includes(pick) && count !== (pick === "both" ? 2 : 3)) return;
  if (["them all","all","all of them","all three","all the facts","both"].includes(pick))
    return facts.map((_, i) => i);
  const terms = pick.replace(/\b(?:the|facts?|ones?|number)\b/g," ").trim().split(/\s*(?:,\s*(?:and\s+)?|\band\b)\s*/);
  const indexes = terms.map(term => {
    const ordinal = [["1","one","first"],["2","two","second"],["3","three","third"]].findIndex(group => group.includes(term.trim()));
    if (ordinal !== -1) return ordinal;
    const words = term.trim().split(/\s+/);
    if (!words.every(w => /^[\p{L}\p{N}]{3,}$/u.test(w)) || /\b(?:not|except|exclude|skip)\b/.test(term)) return -1;
    const matches = facts.map((f,i) => {
      const tokens = f.text.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
      return words.every(w => tokens.some(t => t === w || (w.length >= 5 && [w+"ed",w+"s",w+"ing"].includes(t)))) ? i : -1;
    }).filter(i => i !== -1);
    return matches.length === 1 ? matches[0] : -1;
  });
  if (indexes.every(i => i >= 0 && i < count)) return [...new Set(indexes)];
}

export function verifiedFacts(items, rows) {
  const result = [];
  for (const item of Array.isArray(items) ? items : []) {
    const row = rows.find(r => r.url === item?.url);
    if (!row || typeof item.text !== "string" || !item.text.trim() || item.text.length > 180 ||
        typeof item.quote !== "string" || item.quote.trim().length < 10 ||
        ![row.title,row.snippet].some(s => s?.includes(item.quote)) ||
        !/^https?:\/\//i.test(row.url) || result.some(r => r.text === item.text.trim())) continue;
    result.push({text:item.text.trim(),url:row.url});
    if (result.length === 3) break;
  }
  return result;
}

export async function reviewPortfolioFacts(session, rows) {
  function readReview() {
    const text = session.getLastAssistantText()?.trim() || "";
    try {
      const items = JSON.parse(text.replace(/^`{3}(?:json)?\s*|\s*`{3}$/g,""));
      if (Array.isArray(items)) return verifiedFacts(items, rows);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  const facts = readReview();
  if (facts) return facts;
  await session.prompt(
    "The search is complete. Use the Brave results already in this conversation. " +
    "Give your final answer now as a JSON array, with a short text, exact url, and verbatim " +
    "supporting quote for each candidate. Omit contact details. Return [] if none qualify.",
    {expandPromptTemplates:false},
  );
  await session.waitForIdle();
  const last = session.state.messages.at(-1);
  if (last?.role !== "assistant" || last.stopReason !== "stop") throw Error("Pi could not finish reviewing the search results.");
  return readReview() || [];
}

export async function searchName(profile) {
  let body;
  try { body = await readFile(join(profile,"USER.md"), "utf8"); }
  catch (err) { if (err.code === "ENOENT") return; throw err; }
  if (Buffer.byteLength(body) > 8192) return;
  const lines = body.replace(/<!-- ME3 remembered -->[\s\S]*?<!-- \/ME3 remembered -->|<!--[\s\S]*?-->/g,"").split(/\r?\n/);
  for (const label of ["Public search name","Full name, if useful"]) {
    const matches = lines.filter(l => l.startsWith("- "+label+":")).map(l => l.slice(label.length+3).trim()).filter(Boolean);
    if (matches.length === 1 && /^[\p{L}\p{N}][\p{L}\p{M}\p{N} .’'_-]{0,95}$/u.test(matches[0]))
      return {name:matches[0],approved:label === "Public search name"};
  }
}

export function spokenSearchName(text) {
  return /^(?:please search for|search for|my name is) ([\p{L}\p{N}][\p{L}\p{M}\p{N} .’'_-]{0,95}?)\s*[.!?]?$/iu.exec(text.trim())?.[1].trim();
}

export function confirmSearchName(name) {
  return "May I search Brave for "+name+" and use the configured model to review the public work I find?";
}

export async function newPortfolioReview(profile, explicitLookup) {
  const identity = await searchName(profile);
  if (!identity) return {id:randomUUID(), controller:new AbortController(),
    nameQuestion:"Which name should Pi look up? Say search for, followed by your name."};
  const nameQuestion = explicitLookup && identity.approved ? undefined :
    confirmSearchName(identity.name);
  return {name:identity.name, id:randomUUID(), controller:new AbortController(), nameQuestion};
}

export async function researchPortfolio(name, signal) {
  if (!process.env.BRAVE_SEARCH_API_KEY) throw Error("Portfolio research needs BRAVE_SEARCH_API_KEY.");
  const dir = await mkdtemp(join(tmpdir(), "me3-research-"));
  try {
    const agent = join(dir, "agent");
    await mkdir(agent, {mode:0o700});
    const env = {...workerEnv(process.env,process.env.ME3_CLIENT_HOME), PI_CODING_AGENT_DIR:agent,
      BRAVE_SEARCH_API_KEY:process.env.BRAVE_SEARCH_API_KEY};
    delete env.ME3_VOICE_PROMPT_DIR;
    const path = fileURLToPath(new URL("./worker.mjs",import.meta.url));
    return await new Promise((resolve,reject) => {
      const child = execFile(process.execPath,[path,"--portfolio-research"],{cwd:dir,env,signal,timeout:90000,maxBuffer:100000},(err,out) => {
        try {
          const data = JSON.parse(out);
          if (err || data.error) throw Error(data.error || "Portfolio research failed.");
          if (!data.facts?.length) throw Error("Brave returned no supported work details for review.");
          resolve(data.facts);
        } catch (error) { reject(err && !out ? Error("Portfolio research stopped or timed out.") : error); }
      });
      child.stdin.on("error", () => {});
      child.stdin.end(JSON.stringify({prompt:name}));
    });
  } finally { await rm(dir,{recursive:true,force:true}); }
}

// Interrupting the voice turn releases this waiter. The session owns the worker.
export function waitForResearch(pending, signal) {
  signal.throwIfAborted();
  return new Promise((resolve,reject) => {
    const abort = () => reject(Error("Portfolio review interrupted."));
    signal.addEventListener("abort",abort,{once:true});
    pending.then(resolve,reject).finally(() => signal.removeEventListener("abort",abort));
  });
}
