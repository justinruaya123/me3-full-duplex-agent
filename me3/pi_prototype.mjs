// Pi owns inference. The host exposes only a static, read-only loopback preview.
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const maxBytes = 14 * 1024;
const setup = "Run ./scripts/setup-openintelligentui.sh to install the prototype renderer.";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../.local/openintelligentui-renderer");
const policy = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
const elements = new Set(("style main header footer section article aside nav div span p h1 h2 h3 h4 h5 h6 " +
  "strong em b i u small s sub sup mark time pre code blockquote hr br ul ol li dl dt dd " +
  "table caption thead tbody tfoot tr th td colgroup col figure figcaption details summary " +
  "label input select option optgroup textarea button fieldset legend meter progress output").split(" "));
const attributes = new Set(("id class style title role lang dir open hidden name value placeholder checked " +
  "disabled selected multiple min max step low high optimum for size rows cols colspan rowspan " +
  "scope start reversed maxlength readonly tabindex").split(" "));
const inputTypes = new Set("checkbox radio range text search number date time color month week".split(" "));

export function prototypeRequest(text) {
  return /^(?:(?:please|can you|could you|would you)\s+)*(?:prototype\b|mock\s+up\b|(?:make|build|create|design|generate|stream|show)(?:\s+me)?\s+(?:(?:a|an|the|another|new|streaming|interactive|quick|live|ui|website|web|page)\s+)*(?:prototype|mockup|mock-up)\b)/i.test((text ?? "").trim());
}

export async function loadRenderer() {
  let parser, upstream;
  try {
    parser = createRequire(path.join(root, "package.json"))("parse5");
    upstream = await import(pathToFileURL(path.join(root, "process-partial-html.mjs")).href);
  } catch (error) {
    throw new Error(setup, {cause:error});
  }
  function clean(parent) {
    parent.childNodes = parent.childNodes.flatMap(node => {
      if (node.nodeName === "#text") return [node];
      if (node.namespaceURI !== "http://www.w3.org/1999/xhtml") return [];
      if (["a", "form"].includes(node.tagName)) {
        clean(node);
        return node.childNodes;
      }
      if (!elements.has(node.tagName)) return [];
      if (node.tagName === "input") {
        const type = node.attrs.find(attr => attr.name === "type")?.value.toLowerCase() || "text";
        if (!inputTypes.has(type)) return [];
      }
      node.attrs = node.attrs.filter(({name}) => attributes.has(name) || name.startsWith("aria-")
        || (node.tagName === "input" && name === "type"));
      clean(node);
      return [node];
    });
  }
  return html => {
    const content = upstream.extractCompleteStyles(html) + upstream.processPartialHtml(html);
    const fragment = parser.parseFragment(content);
    clean(fragment);
    return '<!doctype html><html><head><meta charset="utf-8">' +
      '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pi prototype</title></head>' +
      '<body>' + parser.serialize(fragment) + '</body></html>';
  };
}

const page = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi prototype</title><style>body{margin:0;display:grid;grid-template-rows:auto 1fr;height:100dvh;font:14px system-ui}
header{padding:8px 16px;background:#f0f2f5;color:#263549}iframe{border:0;width:100%;height:100%}</style></head>
<body><header aria-live="polite">Streaming prototype…</header><iframe sandbox title="Generated prototype"></iframe>
<script src="preview.js"></script></body></html>`;
const client = `let revision = -1;
async function refresh() {
  const header = document.querySelector("header");
  try {
    const response = await fetch("state", {cache:"no-store"});
    if (!response.ok) throw Error();
    const state = await response.json();
    if (state.revision !== revision) {
      document.querySelector("iframe").srcdoc = state.html;
      revision = state.revision;
    }
    if (state.done) header.textContent = "Saved · " + state.filename;
    else setTimeout(refresh, 250);
  } catch { header.textContent = "Preview closed"; }
}
refresh();`;

function makePreview(render) {
  const prefix = "/" + randomUUID() + "/";
  let raw = "", revision = 0, html, filename, address, expiry;
  const server = createServer({headersTimeout:5000, requestTimeout:5000}, (req, res) => {
    const headers = {"Cache-Control":"no-store", "Referrer-Policy":"no-referrer",
      "X-Content-Type-Options":"nosniff", "X-Frame-Options":"DENY",
      "Content-Security-Policy":"default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"};
    function send(status, type, body) {
      res.writeHead(status, {...headers, "Content-Type":type});
      res.end(body);
    }
    if (req.headers.host !== address || !req.url.startsWith(prefix)) return send(404, "text/plain", "");
    if (req.method !== "GET") return send(405, "text/plain", "");
    switch (req.url.slice(prefix.length)) {
      case "": return send(200, "text/html; charset=utf-8", page);
      case "preview.js": return send(200, "text/javascript", client);
      case "state": {
        try {
          html ??= render(raw);
          return send(200, "application/json", JSON.stringify({html, revision, done:Boolean(filename), filename}));
        } catch { return send(422, "text/plain", "Invalid prototype content"); }
      }
      default: return send(404, "text/plain", "");
    }
  });
  server.maxConnections = 16;
  function close() {
    clearTimeout(expiry);
    server.close();
    server.closeAllConnections();
  }
  return {
    async open() {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
      });
      address = "127.0.0.1:" + server.address().port;
      server.unref();
      expiry = setTimeout(close, 15 * 60 * 1000);
      expiry.unref();
      return "http://" + address + prefix;
    },
    update(value) { if (value !== raw) { raw = value; html = undefined; revision++; } },
    finish(value, name) { html = value; filename = name; revision++; },
    close,
  };
}

export function registerPrototype(pi, { getTurn, ask, message }) {
  let active;
  function dispose() {
    active?.preview?.close();
    active = undefined;
  }
  function check(entry, signal) {
    if (signal?.aborted || active !== entry || getTurn()?.id !== entry.turnId) {
      throw Error("Prototype request expired.");
    }
  }
  async function authorize(entry, signal) {
    check(entry, signal);
    const turn = getTurn();
    if (turn.isCurrent && !(await turn.isCurrent())) throw Error("Prototype request expired.");
    check(entry, signal);
  }
  function reserve(call, signal) {
    const turn = getTurn();
    if (signal?.aborted || !turn?.id || !prototypeRequest(turn.text)) {
      throw Error("Ask explicitly to prototype a page in this chat.");
    }
    if (active?.call === call && active.turnId !== turn.id) throw Error("Prototype request expired.");
    if (active?.turnId === turn.id) {
      if (active.call !== call || active.done) throw Error("One prototype per request.");
      return active;
    }
    dispose();
    const entry = {call, turnId:turn.id};
    active = entry;
    entry.ready = (async () => {
      entry.render = await loadRenderer();
      await authorize(entry, signal);
      entry.preview = makePreview(entry.render);
      try {
        entry.url = await entry.preview.open();
        await authorize(entry, signal);
        message("Streaming prototype · " + entry.url);
      } catch (error) {
        entry.preview.close();
        throw error;
      }
    })();
    return entry;
  }

  pi.on("message_update", async ({assistantMessageEvent: event}) => {
    if (!["toolcall_start", "toolcall_delta", "toolcall_end"].includes(event.type)) return;
    const call = event.toolCall ?? event.partial.content[event.contentIndex];
    if (call?.name !== "me3_prototype" || !call.id) return;
    try {
      const entry = reserve(call.id);
      await entry.ready;
      check(entry);
      const html = call.arguments?.html;
      if (typeof html === "string" && Buffer.byteLength(html) <= maxBytes && !entry.finishing) {
        entry.preview.update(html);
      }
    } catch { /* The actual tool execution reports authorization/setup failures to Pi. */ }
  });
  pi.registerTool({
    name:"me3_prototype", label:"Stream prototype",
    description:"When explicitly asked to prototype or mock up a page, stream a single self-contained HTML/CSS prototype in html. Put compact CSS first, then body markup. Use native controls (checkboxes, sliders, details). Scripts, frames, images, navigation and external assets are unavailable. The host provides a private live preview and saves the finished HTML.",
    parameters:{type:"object", properties:{html:{type:"string", minLength:1, maxLength:maxBytes}},
      required:["html"], additionalProperties:false},
    async execute(id, {html}, signal) {
      if (typeof html !== "string" || !html.trim() || Buffer.byteLength(html) > maxBytes || html.includes("\0")) {
        throw Error("Provide up to 14 KiB of HTML/CSS.");
      }
      const entry = active;
      if (!entry || entry.call !== id || entry.done) throw Error("Prototype request expired.");
      check(entry, signal);
      if (entry.finishing) throw Error("Prototype already finalizing.");
      entry.finishing = true;
      await entry.ready;
      try {
        await authorize(entry, signal);
        const document = entry.render(html);
        if (Buffer.byteLength(document) > 16384) throw Error("Rendered prototype exceeds the 16 KiB file limit.");
        const filename = "prototype-" + randomUUID().slice(0, 8) + ".html";
        await ask("save", filename + " = " + document, entry.turnId);
        check(entry, signal);
        entry.preview.finish(document, filename);
        entry.done = true;
        return {content:[{type:"text", text:"Saved " + filename + " in this chat. Preview: " + entry.url}], details:{filename}};
      } catch (error) {
        if (active === entry) dispose();
        throw error;
      }
    },
  });
  pi.on("agent_end", () => { if (!active?.done) dispose(); });
  pi.on("session_shutdown", dispose);
}
