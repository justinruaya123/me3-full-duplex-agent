import {Type} from "typebox";
import {Text, truncateToWidth} from "@earendil-works/pi-tui";
import {LiveCanvas, mountCanvas} from "./canvas.mjs";

import {presentCanvas, windowUpdate} from "./visual.mjs";

const names = ["show_dashboard", "update_dashboard"];
const choice = (...values) => Type.Union(values.map(s => Type.Literal(s)));
const row = Type.Object({
  kind:choice("note","option","task"),
  label:Type.String({minLength:1,maxLength:80}),
  detail:Type.Optional(Type.String({maxLength:140})),
  marked:Type.Optional(Type.Boolean())
});

export function dashboard(pi, isCurrent) {
  const view = new LiveCanvas();
  let unmount;
  function restore(ctx) {
    const last = ctx.sessionManager.getBranch().findLast(e => e.type === "message" &&
      e.message.role === "toolResult" && names.includes(e.message.toolName) &&
      !e.message.isError && e.message.details?.dashboard);
    view.board = undefined;
    if (last) view.save(last.message.details.dashboard);
    else view.cancel();
  }
  pi.on("session_start", (_,ctx) => {
    if (process.env.ME3_WINDOW_DIR) {
      let previous;
      let timer;
      view.changed = () => {
        if (timer) return;
        timer = setTimeout(() => {
          timer = undefined;
          const board = view.draft || view.board;
          const state = JSON.stringify(board);
          if (board && state !== previous) windowUpdate("canvas", {board, done:!view.draft});
          previous = state;
        }, 80);
      };
      unmount = () => { clearTimeout(timer); view.changed = () => {}; };
    } else if (ctx.hasUI) unmount = mountCanvas(ctx.ui, view, truncateToWidth);
    restore(ctx);
  });
  pi.on("session_tree", (_,ctx) => restore(ctx));
  pi.on("session_shutdown", () => {unmount?.(); unmount = undefined;});
  pi.on("message_update", ({assistantMessageEvent}) => {
    if (!isCurrent()) return;
    view.stream(assistantMessageEvent);
    const call = assistantMessageEvent?.toolCall || assistantMessageEvent?.partial?.content?.[assistantMessageEvent.contentIndex];
    if (call?.name === "show_dashboard" && view.draft) presentCanvas(call.id);
  });
  pi.on("message_end", ({message}) => {
    if (message.role === "assistant" && message.stopReason !== "toolUse") view.cancel();
  });
  pi.on("agent_settled", () => view.cancel());
  function result() {
    const dashboard = structuredClone(view.board);
    return {content:[{type:"text",text:JSON.stringify(dashboard)}],details:{dashboard}};
  }
  const display = {
    renderCall:(_args, theme) => new Text(theme.fg("muted","Dashboard"),0,0),
    renderResult:(res, _opts, theme) => new Text(
      theme.fg(res.details?.dashboard ? "dim" : "warning",
        res.details?.dashboard ? res.details.dashboard.title : cleanError(res)),0,0)
  };
  function cleanError(res) {
    return String(res.content?.[0]?.text || "Dashboard update failed").replace(/[\x00-\x1f\x7f-\x9f]/g," ").slice(0,120);
  }
  pi.registerTool({
    name:names[0], label:"Show task dashboard", ...display,
    description:"Create or revise the current chat's personal dashboard for a plan, checklist, or comparison. Display short rows and meaningful tradeoffs. Options can be selected and tasks checked by voice. Preserve the user's selection when revising. Use supplied facts or label assumptions. A displayed task is a note, not a submitted job.",
    parameters:Type.Object({title:Type.String({minLength:1,maxLength:72}),rows:Type.Array(row,{minItems:1,maxItems:8})}),
    async execute(_call,args,signal) {
      if (signal.aborted || !isCurrent()) throw Error("The request changed.");
      view.save(args);
      presentCanvas(_call);
      return result();
    }
  });
  pi.registerTool({
    name:names[1], label:"Update dashboard row", ...display,
    description:"Apply the user's spoken or typed selection or completion to the existing dashboard. Resolve the label from the board and use its one-based row number. This changes display state only.",
    parameters:Type.Object({row:Type.Integer({minimum:1,maximum:8}), action:choice("select","check","uncheck")}),
    async execute(_call,{row,action},signal) {
      if (signal.aborted || !isCurrent()) throw Error("The request changed.");
      view.change(row,action);
      presentCanvas(_call);
      return result();
    }
  });
  return view;
}
