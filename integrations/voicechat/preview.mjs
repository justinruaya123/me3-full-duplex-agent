// Pi owns inference. The host exposes only a static, read-only loopback preview.
import { createRequire } from "node:module";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const setup = "Run ./scripts/setup-openintelligentui.sh to install the prototype renderer.";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.local/openintelligentui-renderer");
const policy = "default-src 'none'; style-src 'unsafe-inline'; font-src 'none'; base-uri 'none'; form-action 'none'";
const elements = new Set(("main header footer section article aside nav div span p h1 h2 h3 h4 h5 h6 " +
  "strong em b i u small s sub sup mark time pre code blockquote hr br ul ol li dl dt dd " +
  "table caption thead tbody tfoot tr th td colgroup col figure figcaption details summary " +
  "label input select option optgroup textarea button fieldset legend meter progress output").split(" "));
const attributes = new Set(("title lang dir open name value placeholder checked " +
  "disabled selected multiple min max step low high optimum for size rows cols colspan rowspan " +
  "scope start reversed maxlength readonly").split(" "));
const inputTypes = new Set("checkbox radio range text search number date time color month week".split(" "));

export async function loadRenderer() {
  let parser, upstream, katex;
  try {
    const require = createRequire(path.join(root, "package.json"));
    parser = require("parse5");
    katex = require("katex");
    upstream = await import(pathToFileURL(path.join(root, "process-partial-html.mjs")).href);
  } catch (error) {
    throw new Error(setup, {cause:error});
  }
  function mathText(node) {
    const pieces = [], text = node.value;
    const expressions = /\\\[([\s\S]{1,1500}?)\\\]|\\\(([\s\S]{1,1500}?)\\\)|\$\$([\s\S]{1,1500}?)\$\$/g;
    let index = 0;
    for (const match of text.matchAll(expressions)) {
      pieces.push({...node, value:text.slice(index, match.index)});
      try {
        const markup = katex.renderToString(match[1] || match[2] || match[3], {
          output:"mathml", displayMode:!match[2], trust:false, maxExpand:64, maxSize:12
        });
        pieces.push(...parser.parseFragment(markup).childNodes);
      } catch { pieces.push({...node,value:match[0]}); }
      index = match.index + match[0].length;
    }
    return [...pieces, {...node,value:text.slice(index)}];
  }
  function clean(parent) {
    parent.childNodes = parent.childNodes.flatMap(node => {
      if (node.nodeName === "#text") return ["style","pre","code","textarea"].includes(parent.tagName) ? [node] : mathText(node);
      if (node.namespaceURI !== "http://www.w3.org/1999/xhtml") return [];
      if (["a", "form"].includes(node.tagName)) {
        clean(node);
        if (node.tagName === "a") {
          const href = node.attrs.find(attr => attr.name === "href")?.value;
          if (href && href.length <= 2048 && /^https?:\/\//i.test(href)) {
            node.childNodes.push({nodeName:"#text",value:" (" + href + ")"});
          }
        }
        return node.childNodes;
      }
      if (!elements.has(node.tagName)) return [];
      if (node.tagName === "input") {
        const type = node.attrs.find(attr => attr.name === "type")?.value.toLowerCase() || "text";
        if (!inputTypes.has(type)) return [];
      }
      node.attrs = node.attrs.filter(({name}) => attributes.has(name) || ["aria-label","aria-description"].includes(name)
        || (node.tagName === "input" && name === "type"));
      clean(node);
      return [node];
    });
  }
  return html => {
    const content = upstream.processPartialHtml(html);
    const fragment = parser.parseFragment(content);
    clean(fragment);
    return '<!doctype html><html><head><meta charset="utf-8">' +
      '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' +
      '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pi canvas</title><style>body{margin:0;padding:clamp(1rem,4vw,2.5rem);font:17px/1.55 system-ui;color:#172b24;overflow-wrap:anywhere}math[display=block]{margin:1.2em 0}*{box-sizing:border-box}</style><!--me3-reading-style--></head>' +
      '<body>' + parser.serialize(fragment) + '</body></html>';
  };
}
