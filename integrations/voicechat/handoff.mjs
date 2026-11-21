// Older log-only calls lack a microphone item ID. Require a wording match for those.
function words(text) {
  return text.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

function grounded(text, prompt) {
  const excerpt = words(prompt).join("");
  if (!excerpt) return false;
  const tokens = words(text);
  if (tokens.join("") === excerpt) return true;
  if (excerpt.length < 8) return false;
  for (let i = 0; i < tokens.length; i++) {
    let value = "";
    for (let j = i; j < tokens.length && value.length < excerpt.length; j++) {
      value += tokens[j];
      if (!excerpt.startsWith(value)) break;
      if (value === excerpt) return true;
    }
  }
  return false;
}

export class VoiceHandoff {
  constructor(send, receipt, {delegatesOnly = false} = {}) {
    this.delegatesOnly = delegatesOnly;
    this.send = send;
    this.receipt = receipt;
  }

  start(item) {
    this.flush();
    this.close();
    this.item = item;
  }

  final(id, text) {
    if ((this.item && id !== this.item) || this.turn?.id === id) return;
    this.flush();
    this.turn = {id, text};
    if (this.match()) return;
    // Ordinary conversation still proceeds if the model never proposes a tool.
    if (this.delegatesOnly) return;
    this.timer = setTimeout(() => this.flush(), 120);
  }

  propose(call) {
    if (!this.item || this.turn?.call || (call.item && call.item !== this.item)) return;
    this.pending = call;
    this.match();
  }

  match() {
    const turn = this.turn, call = this.pending;
    if (!turn || !call || this.item !== turn.id ||
        !(call.item ? call.item === turn.id : grounded(turn.text, call.text))) return false;
    turn.call = call;
    this.pending = undefined;
    this.flush();
    if (turn.accepted) this.receipt(turn, call);
    return true;
  }

  flush() {
    clearTimeout(this.timer);
    if (this.turn && !this.turn.dispatched && (!this.delegatesOnly || this.turn.call)) {
      this.turn.dispatched = true;
      this.turn.accepted = this.send(this.turn);
    }
  }

  close() {
    clearTimeout(this.timer);
    this.item = this.pending = this.turn = undefined;
  }
}
