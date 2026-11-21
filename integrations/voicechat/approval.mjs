export async function approveDesktopInput(actions, current, ask) {
  if (!current() || !Array.isArray(actions) || !actions.length) return false;
  const labels = {typeText:"type text", setText:"replace text", keypress:"press keys", moveMouse:"move the pointer"};
  const steps = actions.map(step => labels[step.action] || step.action);
  return await ask("May I " + steps.join(", then ") + " in the selected app?") === true && current();
}

// Each promise belongs to one local tool invocation. Only input begun after
// this question's speaker receipt can answer it.
export class SpokenApproval {
  ask(id, signal, tool = "create_website") {
    if (this.pending || signal.aborted) return Promise.resolve(false);
    this.id = id;
    this.tool = tool;
    this.heard = false;
    this.item = undefined;
    return new Promise(resolve => {
      const cancel = () => this.close(false);
      const timer = setTimeout(cancel, 45000);
      signal.addEventListener("abort", cancel, {once:true});
      this.pending = approved => {
        clearTimeout(timer);
        signal.removeEventListener("abort", cancel);
        resolve(approved);
      };
    });
  }
  played(id) {
    if (this.pending && id === this.id) this.heard = true;
  }
  onset(item) {
    this.item = this.heard ? item : undefined;
  }
  answer(item, text) {
    if (!this.pending) return undefined;
    if (!this.heard || item !== this.item) return "unheard";
    const words = text.toLowerCase().replace(/’/g, "'").replace(/[.,!?]/g, " ")
      .trim().replace(/\s+/g, " ");
    const preference = words.replace(/^(?:i'd rather|i would rather) /, "");
    const assent = /^(?:yes|yeah|yep)(?: please)?$/.test(words);
    const action = preference.replace(/^(?:yes|yeah|yep) /, "").replace(/^please /, "");
    const yes = assent || action === "go ahead" || words === "please do"
      || (this.tool === "create_website" && /^(?:go ahead and )?(?:build|create) it$/.test(action));
    const no = /^(?:no(?: thanks| thank you)?|nope)$/.test(words)
      || /^(?:skip it|cancel(?: it)?|don't (?:build|create) it)$/.test(preference.replace(/^no /, ""));
    this.close(yes);
    return yes ? "approved" : no ? "declined" : "unclear";
  }
  close(approved = false) {
    const resolve = this.pending;
    this.pending = this.item = this.id = this.tool = undefined;
    this.heard = false;
    resolve?.(approved);
  }
}
