// Read-only projection of the local voice sidecar. A match here never dispatches a turn.
const words = text => String(text || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
  .replace(/\b(?:bmo|bimo|bee mo|be mo)\b/g, "beemo");

export function expression(state, workerRunning = false, now = Date.now()) {
  if (state.speaking) return "speaking";
  if (state.listening || state.wakeUntil > now) return "listening";
  if (state.foreground || workerRunning) return "thinking";
  return "idle";
}

export class WindowVoice {
  constructor(phrase = "Hey Beemo") {
    this.finishedReceipts = new Set();
    this.phrase = words(phrase) || "hey beemo";
    this.state = {wakePhrase:phrase || "Hey Beemo", mic:"off", asr:"", output:"", foreground:false, speaking:false,
                  listening:false, wakeUntil:0};
  }

  audio(e, followUp = false) {
    const s = this.state;
    switch (e.kind) {
      case "starting": case "off": case "error": case "ready":
        this.item = undefined;
        this.pausedSpeech = false;
        Object.assign(s, {mic:e.kind === "ready" ? "on" : e.kind,
                          listening:false, speaking:false, wakeUntil:0});
        break;
      case "onset":
        this.item = e.id;
        s.asr = "";
        s.listening = followUp || this.pausedSpeech || s.wakeUntil > Date.now();
        s.wakeUntil = 0;
        break;
      case "partial": case "final": {
        if (this.item !== e.id || !e.id) return false;
        s.asr = String(e.text || "").slice(-4000);
        const spoken = words(s.asr);
        if ((" " + spoken + " ").includes(" " + this.phrase + " ")) s.listening = true;
        break;
      }
      case "commit": case "discard":
        if (this.item !== e.id || !e.id) return false;
        this.item = undefined;
        s.wakeUntil = e.kind === "commit" && words(s.asr) === this.phrase ? Date.now() + 8000 : 0;
        s.listening = false;
        s.speaking = e.kind === "discard" && !!this.pausedSpeech;
        this.pausedSpeech = false;
        break;
      case "paused":
        this.pausedSpeech ||= s.speaking;
        s.speaking = false;
        break;
      case "playing":
        if (e.receipt && this.finishedReceipts.has(e.receipt)) return false;
        this.playingReceipt = e.receipt;
        this.pausedSpeech = false;
        s.speaking = true;
        s.wakeUntil = 0;
        break;
      case "played": case "interrupted": {
        const receipt = e.receipt || this.playingReceipt;
        if (receipt) {
          this.finishedReceipts.add(receipt);
          if (this.finishedReceipts.size > 32) this.finishedReceipts.delete(this.finishedReceipts.values().next().value);
          if (this.playingReceipt && receipt !== this.playingReceipt) return false;
        }
        this.playingReceipt = undefined;
        this.pausedSpeech = false;
        s.speaking = false;
        break;
      }
      default: return false;
    }
    return true;
  }
}
