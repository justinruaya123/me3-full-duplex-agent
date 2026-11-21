function spokenMath(formula) {
  const words = formula.trim()
    .replace(/\\frac\{([a-zA-Z]|\d+)\}\{([a-zA-Z]|\d+)\}/g, "$1 over $2")
    .replace(/\\(?:times|cdot)\b/g, " times ")
    .replace(/\\div\b/g, " divided by ")
    .replace(/\^(?:\{2\}|2(?!\d))/g, " squared ")
    .replace(/\^(?:\{3\}|3(?!\d))/g, " cubed ")
    .replace(/=/g, " equals ").replace(/\+/g, " plus ").replace(/-/g, " minus ")
    .replace(/\*/g, " times ").replace(/\//g, " over ");
  // Preserve grouping and unfamiliar operators in the visual formula.
  return /^[a-zA-Z0-9.\s]+$/.test(words) ? words.trim() : "the formula in Pi";
}

// Pi retains the original formatted answer. Normalize only its spoken rendition.
export function spokenReply(value) {
  const text = value.replace(/\r\n?/g, "\n");
  const hasCode = /^ {0,3}(`{3,}|~{3,})/m.test(text);
  const hasLink = /(?:https?:\/\/|www\.)/i.test(text);
  const prose = text
    .replace(/^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}\1[ \t]*$|(?![\s\S]))/gm, " ")
    .replace(/^\s*(?:#{1,6}\s*)?\**(?:sources|references|citations)\**\s*:?\**\s*\n(?:\s*(?:[-*]|\d+[.)])?\s*(?:\[[^\n]+|https?:\/\/[^\n]+)[^\n]*\n?)+/gim, " ")
    .replace(/^\s*\[[^\]\n]+\]:\s*\S+[^\n]*$/gm, " ")
    .replace(/!?\[([^\]\n]*)\]\((?:[^()\s]|\([^()]*\))+(?:\s+"[^"]*")?\)/g, "$1")
    .replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g,
      (_match, block, display, inline) => spokenMath(block ?? display ?? inline))
    .replace(/\$(?!\s)([^$\n]*?\S)\$(?![\d$])/g, (_match, expr) => spokenMath(expr))
    .replace(/\$(\d+(?:,\d{3})*(?:\.\d+)?)/g, (_match, amount) =>
      amount + (Number(amount.replaceAll(",", "")) === 1 ? " dollar" : " dollars"))
    .replace(/\[([^\]\n]+)\]\[[^\]\n]*\]/g, "$1")
    .replace(/\[(?:\^?\d+(?:\s*[,–-]\s*\d+)*)\]/g, "")
    .replace(/(?:https?:\/\/|www\.)[^\s<>\])]+/gi, url => url.match(/[.!?,;:]+$/)?.[0] || "")
    .replace(/^\s{0,3}(?:[-*_]\s*){3,}$/gm, "")
    .replace(/^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)/gm, "")
    .replace(/\*{2,3}([^*]+?)\*{2,3}|__([^\n]+?)__/g, (_match, bold, underlined) => bold ?? underlined)
    .replace(/(?<!\w)([*_])(?=\S)(.+?)\1(?!\w)/g, "$2")
    .replace(/([\p{L}\d)])\s*\*\s*(?=[-+]?[\p{L}\d(])/gu, "$1 times ")
    .replace(/[`*]/g, "")
    .replace(/[\x00-\x1f\x7f-\x9f\s]+/g, " ")
    .replace(/\s+([,.;!?])/g, "$1")
    .trim();
  if (/[\p{L}\p{N}]/u.test(prose)) return prose.slice(0,4000).trimEnd();
  if (hasCode) return "The code is in Pi.";
  if (hasLink) return "The link is in Pi.";
  return prose;
}

const sentences = new Intl.Segmenter("en", {granularity:"sentence"});

// Only elliptical replies about the preceding lookup. A new subject or an
// opt-out must go through normal turn routing.
export function recheckRequest(source) {
  const text = source.toLowerCase().replace(/[’]/g, "'").replace(/[.!?,]+/g, " ").trim().replace(/\s+/g, " ");
  return /^(?:(?:yes|yeah|no|okay|please) (?:but )?)?(?:(?:(?:i )?(?:think|thought) )?(?:(?:is|was) there |there(?:'s| was| is) )?(?:some(?:thing)? |anything |a )?(?:more (?:modern|recent)|newer|later|latest)(?: (?:one|there|than that))?|(?:give me (?:a )?|(?:do |run |try )(?:a )?|you're not using (?:a )?)(?:web search|brave search)|(?:please )?(?:search|check|verify|look it up)(?: (?:again|online|with brave|the web|it|that)){0,2})$/.test(text);
}

export function searchFallback(turn) {
  if ((turn?.requiresSearch && !turn.liveEvidence) ||
      ((turn?.lookup || turn?.searchAttempted || turn?.publicLookup) && !turn?.searchSupport))
    return "I couldn’t verify that with a source this time.";
}

// Candidate only. The host still validates the whole public utterance locally.
export function publicFactCheck(source) {
  return /\b(?:when (?:did|was|were|will)|who (?:won|wins|leads)|latest|currently|recent(?:ly)?|as of (?:now|today)|this (?:week|month|year)|verify|fact.check)\b/i.test(source);
}

// A second look is often inconclusive. An older snippet cannot justify a
// model's added claim that no newer event exists.
export function checkedRecheck(reply, evidence) {
  const sentence = spokenReply(reply).replace(/^["“]|["”]$/g, "").trim();
  if (sentence && sentence.length <= 320) {
    for (const line of evidence.split("\n")) {
      for (const {segment} of sentences.segment(line)) {
        if (spokenReply(segment) === sentence) return sentence;
      }
    }
  }
  return "I checked again, but I couldn’t confirm that from the sources I found.";
}

export function spokenToolReply(value) {
  const clean = spokenReply(value);
  if (!clean) return "";
  const selected = [];
  for (const {segment} of sentences.segment(clean)) {
    const line = segment.trim();
    if ([...selected, line].join(" ").split(/\s+/).length > 45) break;
    selected.push(line);
    if (selected.length === 2) break;
  }
  return selected.join(" ") || "The full response is in Pi.";
}

export function jobNotice(job) {
  const subject = job.kind === "website" ? "Your website" : "Your draft";
  if (job.status !== "completed")
    return subject + (job.status === "failed" ? " couldn't be finished." : " was interrupted.");
  const ready = subject + " is ready.";
  if (job.kind !== "draft") return ready;
  const first = job.text?.trimStart().split("\n", 1)[0] || "";
  const line = /^\**Takeaway\**:\**[ \t]+(.+)$/i.exec(first)?.[1];
  if (!line || line.length > 300) return ready;
  const takeaway = spokenReply(line);
  return takeaway && takeaway.split(/\s+/).length <= 30 ? ready + " " + takeaway : ready;
}

// Retrieval timestamps and URLs are metadata. Only cited content can support spoken figures.
export function checkSearchReply(reply, evidence) {
  const numbers = value => value.replace(/(\d),(?=\d{3}\b)/g, "$1").match(/\d+(?:\.\d+)*/g) || [];
  const supported = new Set(numbers(evidence));
  const claims = numbers(spokenReply(reply));
  if (claims.every(number => supported.has(number))) return reply;
  // A speculative second sentence must not erase a supported lead figure.
  const lead = sentences.segment(spokenReply(reply))[Symbol.iterator]().next().value?.segment.trim();
  const figures = numbers(lead || "");
  if (figures.length && figures.every(number => supported.has(number))) return lead;
  return "I couldn’t verify that detail from the search results.";
}

// The next provider pass already has this turn's search receipt, including a failure.
export function afterLookup(payload) {
  if (!Array.isArray(payload?.tools)) return;
  const tools = payload.tools.filter(tool => (tool.function?.name ?? tool.name) !== "web_lookup");
  if (tools.length !== payload.tools.length) return {...payload, tools};
}

// Walk only the preceding completed user turn on this branch.
export function previousSearchReceipt(messages) {
  const current = messages.findLastIndex(message => message.role === "user");
  if (current < 1 || messages[current - 1]?.stopReason !== "stop") return;
  for (let i = current - 2; i >= 0 && messages[i].role !== "user"; i--) {
    const message = messages[i];
    if (message.role === "toolResult")
      return message.toolName === "web_lookup" && !message.isError ? message.details : undefined;
  }
}

// A natural confirmation question may have been spoken without a tool call.
export function lastPublicClarification(messages) {
  const i = messages.findLastIndex(m => m.role === "user");
  const reply = messages[i - 1];
  if (reply?.role !== "assistant" || reply.stopReason !== "stop") return;
  const text = (reply.content || []).filter(c => c.type === "text").map(c => c.text).join(" ");
  return text.match(/(?:^|[.!?]\s+)(?:do you mean|did you mean|(?:want me to|should I) (?:try a narrower search on|look up|search for|check)) ([^.!?]{3,160})\?(?:\s+[^?]*)?$/i)?.[1];
}
