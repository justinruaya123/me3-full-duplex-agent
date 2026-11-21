// A wire final is display evidence. The audio sidecar separately commits the
// same utterance after local endpointing. Replacing this gate fences reconnects.
export class TurnGate {
  onset(id) {
    this.id = id;
    this.text = undefined;
  }
  final(id, text) {
    if (id === this.id) this.text = text;
  }
  commit(id, text) {
    if (!text || id !== this.id || text !== this.text) return false;
    this.onset(undefined);
    return true;
  }
}
