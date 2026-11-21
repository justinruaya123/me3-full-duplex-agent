import {loadRenderer} from "./preview.mjs";
import {writeFileSync,renameSync} from "node:fs";
import {join} from "node:path";

const maxBytes = 14 * 1024;

// The launcher grants only its child Pi process a private, per-window directory.
export function windowUpdate(panel, data) {
  if (!process.env.ME3_WINDOW_DIR) return;
  const path = join(process.env.ME3_WINDOW_DIR, panel + ".json");
  writeFileSync(path + ".new", JSON.stringify(data), {mode:0o600});
  renameSync(path + ".new",path);
}

// Each visual invocation may bring the panel forward once, even as its draft keeps streaming.
let presented;
export function presentCanvas(id) {
  if (id && presented !== id) {
    presented = id;
    windowUpdate("focus", {panel:"canvas", request:id});
  }
}

export function registerVisual(pi, currentTurn, publish = data => windowUpdate("canvas",data), renderer = loadRenderer) {
  let draft, saved, timer, render;
  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    if (draft && draft.turn === currentTurn() && render) publish({html:render(draft.html),done:false});
  };
  function cancel() {
    clearTimeout(timer);
    timer = undefined;
    if (draft) publish(saved || {html:"",done:true});
    draft = undefined;
  }
  pi.on("session_start", async () => {render = await renderer();});
  pi.on("session_tree", () => {cancel(); saved = undefined; publish({html:"",done:true});});
  pi.on("session_shutdown", () => {cancel(); saved = undefined;});
  pi.on("agent_settled", cancel);
  pi.on("message_update", ({assistantMessageEvent:e}) => {
    if (e?.type !== "toolcall_delta" && e?.type !== "toolcall_end") return;
    const call = e.toolCall || e.partial?.content?.[e.contentIndex];
    if (call?.name !== "show_visual" || !call.id) return;
    const html = call.arguments?.html, turn = currentTurn();
    if (!turn || typeof html !== "string" || !html || Buffer.byteLength(html) > maxBytes) return;
    if (draft && (draft.id !== call.id || draft.turn !== turn)) return;
    presentCanvas(call.id);
    draft = {id:call.id,turn,html};
    if (!timer) timer = setTimeout(flush, 80);
  });
  pi.registerTool({
    name:"focus_panel", label:"Show panel",
    description:"Return to the face, show IntelligentUI (canvas), or inspect delegated agent streams when asked.",
    parameters:{type:"object",properties:{panel:{type:"string",enum:["face","canvas","agents"]}},required:["panel"]},
    async execute(_id,{panel},signal) {
      if (!currentTurn() || signal.aborted || !["face","canvas","agents"].includes(panel)) throw Error("Panel request expired.");
      windowUpdate("focus", {panel, request:_id});
      return {content:[{type:"text",text:"Showing " + panel + "."}]};
    }
  });
  pi.registerTool({
    name:"show_visual", label:"Draw on canvas",
    description:"Show or revise a private visual aid in the IntelligentUI view. Send the complete updated view as semantic headings, lists, tables, native controls and math. The host applies the layout and colors. Native controls and disclosures work. Use Unicode and sub/sup for equations. Scripts, external assets and navigation are unavailable. A sketch is separate from a website build.",
    parameters:{type:"object",properties:{html:{type:"string",minLength:1,maxLength:maxBytes}},required:["html"],additionalProperties:false},
    renderCall:()=>({render:()=>["Drawing on canvas…"],invalidate(){}}),
    renderResult:res=>({render:()=>[res.content[0].text],invalidate(){}}),
    async execute(id,{html},signal) {
      const turn = currentTurn();
      if (!turn || signal.aborted || (draft && (draft.id !== id || draft.turn !== turn)))
        throw Error("Visual request expired.");
      if (typeof html !== "string" || !html.trim() || html.includes("\0") || Buffer.byteLength(html)>maxBytes)
        throw Error("Provide up to 14 KiB of semantic HTML.");
      if (!render) throw Error("The local visual renderer is unavailable.");
      clearTimeout(timer);
      timer = draft = undefined;
      saved = {html:render(html),done:true};
      presentCanvas(id);
      publish(saved);
      return {content:[{type:"text",text:"Visual updated."}]};
    }
  });
}
