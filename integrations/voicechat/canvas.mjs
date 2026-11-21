// Display-only data. Partial tool arguments can paint a preview but cannot change a saved board.
const clean = (value, max) => typeof value === "string"
  ? value.slice(0, max).replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, " ").trim() : "";
const kinds = ["note", "option", "task"];

function snapshot(value) {
  return {
    title:clean(value?.title, 72),
    rows:(Array.isArray(value?.rows) ? value.rows.slice(0,8) : []).map(row => ({
      kind:kinds.includes(row?.kind) ? row.kind : "note",
      label:clean(row?.label, 80), detail:clean(row?.detail, 140), marked:row?.marked === true
    }))
  };
}

export class LiveCanvas {
  board;
  draft;
  changed = () => {};

  stream(event) {
    if (event?.type !== "toolcall_delta" && event?.type !== "toolcall_end") return;
    const call = event.toolCall || event.partial?.content?.[event.contentIndex];
    if (call?.name !== "show_dashboard") return;
    this.draft = snapshot(call.arguments);
    this.changed();
  }
  cancel() {
    this.draft = undefined;
    this.changed();
  }
  save(value) {
    const board = snapshot(value);
    if (!board.title || !board.rows.length || board.rows.some(row => !row.label)) {
      throw Error("Give the dashboard a title and label each row.");
    }
    if (board.rows.filter(row => row.kind === "option" && row.marked).length > 1)
      throw Error("Select at most one option.");
    this.board = board;
    this.cancel();
  }
  change(number, action) {
    const target = this.board?.rows[number-1];
    if (!target) throw Error("That row is not on the current dashboard.");
    if (action === "select" && target.kind === "option") {
      for (const row of this.board.rows) if (row.kind === "option") row.marked = row === target;
    } else if ((action === "check" || action === "uncheck") && target.kind === "task") {
      target.marked = action === "check";
    } else throw Error("Select an option, or check or uncheck a task.");
    this.cancel();
  }
  lines() {
    const board = this.draft || this.board;
    if (!board) return [];
    const heading = "╭─ " + (board.title || "Dashboard") + (this.draft ? " · composing" : "");
    const rows = board.rows.filter(row=>row.label).map((row,i) => {
      let marker = "·";
      if (row.kind === "option") marker = row.marked ? "●" : "○";
      if (row.kind === "task") marker = row.marked ? "☑" : "☐";
      return `│ ${i+1}  ${marker}  ${row.label}` + (row.detail ? "  ·  " + row.detail : "");
    });
    return [heading, ...rows, "╰─ Pi canvas"];
  }
}

// One widget and at most one queued redraw while tokens arrive.
export function mountCanvas(ui, view, truncate) {
  let timer;
  ui.setWidget("me3-canvas", (tui, theme) => {
    view.changed = () => {
      if (!timer) timer = setTimeout(() => {timer = undefined; tui.requestRender();}, 60);
    };
    return {
      render(width) {
        return view.lines().map((line,i) => truncate(
          i === 0 ? theme.fg("accent",theme.bold(line)) :
          line.startsWith("╰") ? theme.fg("dim",line) : line, width, "…"));
      },
      invalidate() {}
    };
  });
  return () => {
    clearTimeout(timer);
    view.changed = () => {};
    ui.setWidget("me3-canvas", undefined);
  };
}
