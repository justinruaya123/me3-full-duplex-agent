// A repeatedly failing host should release the mic until the operator retries.
export class VoiceRecovery {
  attempts = [];
  timer;
  schedule(reconnect, now = Date.now()) {
    this.attempts = this.attempts.filter(t => now - t < 60000);
    if (this.timer || this.attempts.length >= 2) return false;
    this.attempts.push(now);
    this.timer = setTimeout(() => {
      this.timer = undefined;
      reconnect();
    }, 750 * this.attempts.length);
    return true;
  }
  reset() {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.attempts = [];
  }
}
