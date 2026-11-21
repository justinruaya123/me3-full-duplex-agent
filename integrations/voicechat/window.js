import {expression} from "./face.mjs";
import {displayVars, readableCanvas, validBoard} from "./display.mjs";

const byId = id => document.getElementById(id);
const term = new Terminal({fontSize:14,cols:90,rows:26,scrollback:800,
  theme:{background:"#141a1a",foreground:"#f5f5ee"}});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(byId("terminal"));
let ws, reconnectTimer, lost = false;
let prefs = {theme:"classic",large:false,still:false}, tokens, pack = {}, currentCanvas;
const readable = () => prefs.theme === "bmo-readable" && tokens;
const dialog = byId("preferences"), publishDialog = byId("publication");
let publication;
function showPublication(value) {
  publication = value;
  if (!value) {
    publishDialog.close();
    return;
  }
  byId("publish-title").textContent = value.title;
  byId("publish-detail").textContent = value.detail;
  for (const id of ["publish-cancel", "publish-confirm"]) byId(id).disabled = false;
  if (!publishDialog.open) publishDialog.showModal();
  byId("publish-cancel").focus();
}
function decidePublication(approved) {
  if (!publication || ws?.readyState !== WebSocket.OPEN || byId("publish-cancel").disabled) return;
  ws.send(JSON.stringify({publication:{id:publication.id,approved}}));
  for (const id of ["publish-cancel", "publish-confirm"]) byId(id).disabled = true;
}
byId("publish-cancel").onclick = () => decidePublication(false);
byId("publish-confirm").onclick = () => decidePublication(true);
publishDialog.oncancel = event => {event.preventDefault(); decidePublication(false);};
const encoder = new TextEncoder();
function input(text) {
  if (ws?.readyState !== WebSocket.OPEN) return;
  const bytes = encoder.encode(text);
  for (let i=0; i<bytes.length; i+=4096) ws.send(bytes.subarray(i,i+4096));
}
term.onData(input);

let panel = "face", voice = {mic:"off"}, jobs = [], selectedJob;
let warmUntil = performance.now() + 1000;
let animationTimer, lastFace, frame = 0;
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
function paintFace(advance = false) {
  clearTimeout(animationTimer);
  if ((panel !== "face" && panel !== "canvas") || document.hidden) return;
  const warm = warmUntil - performance.now();
  const mode = lost || voice.mic === "error" ? "error" : voice.mic === "starting" || warm > 0 ? "warmup" :
    readable() && voice.listening ? "listening" : expression(voice,!readable() && jobs.some(j => j.status === "running"));
  const changed = lastFace !== mode;
  const frames = pack[mode]?.length ? pack[mode] : (pack.idle || []);
  const moving = frames.length > 1 && !reduced.matches && !prefs.still;
  if (changed || !moving) frame = 0;
  else if (advance) frame = mode === "speaking"
    ? 1 + Math.floor(Math.random() * (frames.length - 1))
    : (frame + 1) % frames.length;
  if (changed || advance) {
    const stage = byId("face-stage"), img = byId("face");
    stage.dataset.mode = mode;
    const src = frames[frame];
    img.hidden = !src;
    if (src && img.getAttribute("src") !== src) img.src = src;
    byId("activity").textContent = lost ? "Disconnected" : mode[0].toUpperCase() + mode.slice(1);
  }
  lastFace = mode;
  const next = warm > 0 ? warm : (moving ? (mode === "speaking" ? 50 : 500) : Infinity);
  const wake = voice.wakeUntil > Date.now() ? voice.wakeUntil - Date.now() : Infinity;
  if (Number.isFinite(Math.min(next,wake)))
    animationTimer = setTimeout(() => paintFace(true),Math.max(1,Math.min(next,wake)));
}
function refocus() {warmUntil = performance.now() + 1000; paintFace();}
addEventListener("focus", () => {if (panel === "face") refocus();});
document.addEventListener("visibilitychange", () => document.hidden ? clearTimeout(animationTimer) : refocus());
reduced.addEventListener("change", () => {lastFace = undefined; paintFace();});

function resize() {
  if (panel === "console" && byId("terminal").clientWidth > 0) fit.fit();
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({cols:term.cols,rows:term.rows}));
}
new ResizeObserver(() => {if (panel === "console") resize();}).observe(byId("terminal"));
byId("face").onerror = () => {
  const src = byId("face").getAttribute("src");
  for (const mode in pack) pack[mode] = pack[mode].filter(name => name !== src);
  lastFace = undefined; paintFace();
};
const versions = new Map();
function connect() {
  ws = new WebSocket(new URL("stream", location.href.replace(/^http/,"ws")));
  ws.binaryType = "arraybuffer";
  ws.onmessage = receive;
  ws.onopen = () => {
    if (lost) {term.reset(); term.clear();}
    lost = false; versions.clear(); resize(); byId("duplex").disabled = false;
    lastFace = undefined; captions(); paintFace();
  };
  ws.onclose = disconnected;
}
function disconnected() {

  term.writeln("\r\nPi window disconnected.");
  lost = true; lastFace = undefined;
  showPublication(null);
  captions(); renderJobs(); paintFace();
  byId("duplex").disabled = true;
  clearTimeout(reconnectTimer); reconnectTimer = setTimeout(connect, 1000);
}
byId("duplex").onclick = () => input("/me3 duplex\r");

function show(next) {
  if (!["face","canvas","console","agents"].includes(next)) return;
  panel = next;
  document.body.dataset.view = next;
  const faceHost = byId(next === "canvas" ? "close" : "home");
  if (byId("face-stage").parentElement !== faceHost) faceHost.append(byId("face-stage"));
  byId("home").hidden = next !== "face";
  byId("workspace").hidden = next === "face";
  byId("terminal").hidden = next !== "console";
  byId("visual").hidden = next !== "canvas";
  byId("jobs").hidden = next !== "agents";
  for (const key of ["canvas","console","agents"])
    byId(key).setAttribute("aria-pressed", String(next === key));
  if (next === "face") {
    refocus(); captions(); byId("inspect").focus({preventScroll:true});
  } else {
    paintFace();
    if (next === "console") {resize(); term.focus();}
    else byId(next).focus({preventScroll:true});
  }
}
byId("inspect").onclick = () => show("console");
byId("close").onclick = () => show("face");
for (const key of ["canvas","console","agents"]) byId(key).onclick = () => show(key);
byId("fullscreen").onclick = () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
};
addEventListener("keydown", event => {
  if (event.key === "Escape" && !dialog.open && !publishDialog.open && panel !== "face" && panel !== "console") show("face");
});
function caption(id, text) {
  const line = byId(id);
  if (line.textContent === text) return;
  const atEnd = line.scrollHeight - line.clientHeight - line.scrollTop < 4;
  line.textContent = text;
  if (atEnd) line.scrollTop = line.scrollHeight;
}
function captions() {
  const mic = byId("duplex");
  mic.textContent = lost ? "Mic unknown" : {on:"Mic on",starting:"Starting",error:"Mic error",offline:"Offline"}[voice.mic] || "Mic off";
  mic.title = voice.mic === "on" ? "Turn off microphone · wake phrase: " + voice.wakePhrase : "Turn on microphone";
  if (lost) mic.removeAttribute("aria-pressed");
  else mic.setAttribute("aria-pressed",String(voice.mic === "on"));
  byId("answer").hidden = !voice.output;
  byId("playback-state").hidden = !voice.speaking || lost;
  workStatus();
  caption("asr",voice.asr || ""); caption("output",voice.output || "");
}
function workStatus() {
  const running = jobs.filter(j => j.status === "running").length;
  const ready = jobs.filter(j => j.status === "completed").length;
  byId("work-status").textContent = lost ? "Disconnected · awaiting device status" :
    [byId("duplex").textContent,voice.speaking && "Audio playing",voice.foreground && "Thinking",
      running && running+" working",ready && ready+" ready"].filter(Boolean).join(" · ");
}
function el(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}
function renderJobs() {
  const tabs = byId("job-tabs"), output = byId("job-output"), pane = byId("jobs");
  const atEnd = pane.scrollHeight - pane.clientHeight - pane.scrollTop < 24;
  if (!jobs.some(j => j.id === selectedJob)) selectedJob = jobs.at(-1)?.id;
  const job = jobs.find(j => j.id === selectedJob);
  const ready = jobs.filter(j=>j.status==="completed").length;
  const running = jobs.filter(j=>j.status==="running").length;
  byId("ready-count").hidden = !ready && !running;
  byId("ready-count").textContent = [running && running+" working",ready && ready+(ready===1?" result ready":" results ready")].filter(Boolean).join(" · ");
  const ids = new Set(jobs.map(j => j.id));
  for (const tab of [...tabs.children]) if (!ids.has(tab.dataset.job)) tab.remove();
  for (const [index,j] of jobs.entries()) {
    let tab = [...tabs.children].find(t => t.dataset.job === j.id);
    if (!tab) {
      tab = el("button",j.kind + " " + (index + 1));
      tab.dataset.job = j.id;
      tab.onclick = () => {selectedJob = j.id; renderJobs();};
      tabs.append(tab);
    }
    tab.setAttribute("aria-pressed",String(selectedJob === j.id));
  }
  byId("agents").textContent = jobs.length ? "Agents · " + jobs.length : "Agents";
  workStatus();
  byId("job-status").textContent = job ? [job.agent || job.kind,job.status,"revision " + job.revision].join(" · ") : "No delegated agents yet.";
  const download = byId("job-download");
  download.hidden = !(job?.kind === "website" && job.status === "completed" && job.archive);
  if (download.hidden) download.removeAttribute("href");
  else download.href = "website-" + job.id + "-" + job.revision + ".zip";
  const htmlDownload = byId("job-html");
  htmlDownload.hidden = download.hidden;
  if (htmlDownload.hidden) htmlDownload.removeAttribute("href");
  else htmlDownload.href = `site/${job.id}/${job.revision}/index.html?download=1`;
  if (currentCanvas?.site) renderSite(currentCanvas);
  output.textContent = job?.text || job?.preview || job?.error || job?.index || "";
  if (job?.status === "running" && atEnd) pane.scrollTop = pane.scrollHeight;
}
byId("ready-count").onclick = () => show("agents");
function renderSite({site, revision}) {
  const frame = document.querySelector("iframe");
  const job = jobs.find(entry => entry.id === site && entry.revision === revision && entry.kind === "website");
  const ready = job?.status === "completed" && !!job.archive;
  const preview = job?.status === "running" && job.previewHtml;
  byId("board").replaceChildren();
  const hint = byId("hint");
  hint.textContent = ready ? "" : job?.error || (preview ? "Building website…" : "Waiting for website preview…");
  if (job && ["cancelled","interrupted"].includes(job.status)) hint.textContent = "Website build " + job.status + ".";
  hint.hidden = ready;
  frame.hidden = !(ready || preview);
  frame.inert = !ready;
  frame.title = "Website preview";
  if (ready) {
    const src = `site/${site}/${revision}/index.html`;
    if (frame.getAttribute("src") !== src) frame.setAttribute("src",src);
    frame.removeAttribute("srcdoc");
  } else {
    frame.removeAttribute("src");
    if (preview && frame.getAttribute("srcdoc") !== preview) frame.srcdoc = preview;
    if (!preview) frame.removeAttribute("srcdoc");
  }
}
function renderCanvas(value, force = false) {
  if (/^[a-f0-9]{32}$/.test(value?.site || "") && Number.isSafeInteger(value.revision) && value.revision > 0) {
    currentCanvas = value;
    renderSite(value);
    return;
  }
  const iframe = document.querySelector("iframe"), board = byId("board");
  if (!value || typeof value.done !== "boolean" ||
      (value.board === undefined && value.html === undefined) ||
      (value.board !== undefined && !validBoard(value.board)) ||
      (value.html !== undefined && (typeof value.html !== "string" || value.html.length > 262144 ||
                     (value.html !== "" && !value.html.startsWith("<!doctype html>"))))) {
    byId("hint").hidden = false;
    byId("hint").textContent = "The latest view could not be displayed.";
    return;
  }
  if (!force && !currentCanvas?.site && currentCanvas?.done && value.done === false) return;
  iframe.removeAttribute("src");
  iframe.title = "IntelligentUI visual";
  currentCanvas = value;
  byId("hint").textContent = "Your dashboard will appear here.";
  byId("hint").hidden = !!(value.board || value.html);
  iframe.hidden = !value.html;
  board.replaceChildren();
  iframe.inert = value.done === false;
  if (value.html) iframe.srcdoc = readable() ? readableCanvas(value.html,tokens,prefs.large,prefs) : value.html;
  else iframe.removeAttribute("srcdoc");
  if (value.board) {
    board.append(el("h2",value.board.title));
    for (const row of value.board.rows) {
      const marker = row.kind === "task" ? (row.marked ? "☑ " : "☐ ") : row.kind === "option" ? (row.marked ? "● " : "○ ") : "";
      const article = el("article", marker + row.label);
      if (row.href) {
        const link = el("a",row.label);
        link.href = row.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        article.replaceChildren(link);
      }
      if (row.detail) article.append(el("p",row.detail));
      board.append(article);
    }
  }
}
function receive({data}) {
  if (typeof data !== "string") {term.write(new Uint8Array(data));return;}
  const update = JSON.parse(data), value = update.data;
  if (update.version) {
    const version = BigInt(update.version);
    if (version <= (versions.get(update.panel) ?? -1n)) return;
    versions.set(update.panel,version);
  }
  switch (update.panel) {
    case "preference_error": byId("pref-status").textContent = value; break;
    case "voice": {
      const before = voice;
      voice = value; captions();
      if (before.mic !== voice.mic || before.listening !== voice.listening ||
          before.wakeUntil !== voice.wakeUntil || expression(before) !== expression(voice)) paintFace();
      break;
    }
    case "agents": jobs = value; renderJobs(); paintFace(); break;
    case "canvas": renderCanvas(value); break;
    case "publication": showPublication(value); break;
    case "focus":
      if (value.request && sessionStorage.getItem("presentation") === value.request) break;
      if (value.request) sessionStorage.setItem("presentation",value.request);
      show(value.panel);
  }
};
function applyAppearance() {
  document.documentElement.dataset.theme = prefs.theme;
  if (tokens) {
    const vars = displayVars(tokens,prefs.large,prefs);
    for (const [key,value] of Object.entries(vars)) {
      if (readable()) document.documentElement.style.setProperty("--"+key,value);
      else document.documentElement.style.removeProperty("--"+key);
    }
    const profile = tokens.terminalStartingProfile;
    Object.assign(term.options, readable() ? {
      fontSize:prefs.large ? 22 : profile.fontSize,fontFamily:profile.fontFamily,lineHeight:profile.lineHeight,
      cursorBlink:false,theme:{foreground:tokens.color.ink,background:vars.paper,cursor:tokens.color.ink,
        selectionBackground:tokens.color.yellow,selectionForeground:tokens.color.ink}
    } : {fontSize:14,fontFamily:'monospace',lineHeight:1,theme:{background:"#141a1a",foreground:"#f5f5ee"}});
  }
  byId("theme-choice").value = prefs.theme;
  byId("large-text").checked = prefs.large;
  byId("still-face").checked = prefs.still;
  for (const key of ["font","spacing","background"]) byId("pref-"+key).value = prefs[key] || "default";
  lastFace = undefined; paintFace();
  if (currentCanvas) renderCanvas(currentCanvas,true);
  if (readable()) document.fonts.load('18px "Atkinson Hyperlegible Mono"').then(resize,resize);
  resize();
}
function saveAppearance() {
  prefs = {theme:byId("theme-choice").value,large:byId("large-text").checked,still:byId("still-face").checked};
  for (const key of ["font","spacing","background"]) prefs[key] = byId("pref-"+key).value;
  applyAppearance();
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({appearance:prefs}));
  else byId("pref-status").textContent = "Disconnected. These settings apply to this window only.";
}
for (const id of ["appearance-home","appearance-work"]) byId(id).onclick = () => dialog.showModal();
dialog.onchange = ({target}) => {
  if (["large-text","pref-font","pref-spacing","pref-background"].includes(target.id)) byId("theme-choice").value = "bmo-readable";
  saveAppearance();
};
byId("pref-done").onclick = () => dialog.close();
byId("pref-reset").onclick = () => {
  prefs = {theme:"classic",large:false,still:false};
  applyAppearance(); saveAppearance();
};
async function startDisplay() {
  try {
    const response = await fetch("display.json");
    if (!response.ok) throw Error("Display settings unavailable");
    const config = await response.json();
    tokens = config.tokens; prefs = config.appearance; pack = config.faces;
    // Keep decoded local frames alive. Subsequent animation ticks do no I/O.
    for (const names of Object.values(pack)) for (const name of names) {
      const img = new Image(); img.src = name; preloaded.push(img);
    }
  } catch { byId("pref-status").textContent = "Using the built-in display."; }
  applyAppearance(); connect();
}
const preloaded = [];
startDisplay();
