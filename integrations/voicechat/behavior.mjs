import {readFileSync} from "node:fs";

export const phrases = JSON.parse(readFileSync(new URL("./behavior/phrases.json", import.meta.url)));
const words = text => text.toLowerCase().replace(/[.,!?]/g, " ").trim()
  .replace(/\s+/g, " ").replace(/\b(?:bmo|bimo|bee mo|be mo)\b/g, "beemo");

export function isWakeGreeting(text, phrase = "Hey BMO") {
  return words(text) === (words(phrase) || "hey beemo");
}

export function cuePicker() {
  const next = new Map();
  return kind => {
    const variants = phrases[kind];
    const i = next.get(kind) || 0;
    next.set(kind, (i + 1) % variants.length);
    return variants[i];
  };
}

export function listenerMode(playedQuestion, protectedPrompt) {
  return {op:"listener", enabled:!protectedPrompt, awaiting_answer:playedQuestion || protectedPrompt};
}

// Owns only the pending foreground response. Tool execution and background jobs
// have separate deadlines; private reasoning tokens are not user-visible progress.
export class VoiceWait {
  constructor(cue, stalled) {
    this.cue = cue;
    this.stalled = stalled;
    this.tools = new Set();
  }
  start(id) {
    this.end(this.id);
    this.id = id;
    this.cueTimer = setTimeout(() => this.cue(id), 2500);
    this.progress(id);
  }
  progress(id) {
    if (!id || this.id !== id || this.tools.size) return;
    clearTimeout(this.deadline);
    this.deadline = setTimeout(() => {
      this.end(id);
      this.stalled(id);
    }, 20000);
  }
  tool(id, callId, started) {
    if (!id || this.id !== id) return;
    if (started) {
      this.tools.add(callId);
      clearTimeout(this.cueTimer);
      clearTimeout(this.deadline);
    } else {
      this.tools.delete(callId);
      this.progress(id);
    }
  }
  end(id = this.id) {
    if (this.id !== id) return;
    clearTimeout(this.cueTimer);
    clearTimeout(this.deadline);
    this.tools.clear();
    this.id = undefined;
  }
}

export function voiceFailure(reason) {
  if (reason === "length") return "I ran out of room to finish that answer.";
  if (reason === "error") return "I couldn't get an answer from the conversation model.";
  return "";
}

export function finishVoiceText(text, turn) {
  if (text.trim() !== "[acknowledged]") return text;
  return turn?.jobCue ? "" : "I don't have a result to report yet.";
}
