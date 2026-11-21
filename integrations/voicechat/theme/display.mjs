// The same operator-supplied roles style the browser, sandboxed canvas and xterm.
export function displayVars(t, large, prefs = {}) {
  const f = t.font;
  return {
    ...t.color, paper:prefs.background === "mint" ? t.color.screen : t.color.paper,
    ui:prefs.font === "system" ? "system-ui,sans-serif" : f.ui.map(name=>name.includes(" ") ? '"'+name+'"' : name).join(","),
    mono:t.terminalStartingProfile.fontFamily, "body-size":(large?f.largeBodySizeRem:f.bodySizeRem)+"rem",
    "caption-size":(f.captionSizeRem/f.bodySizeRem)+"em", "code-size":(f.codeSizeRem/f.bodySizeRem)+"em",
    leading:prefs.spacing === "wide" ? 1.7 : f.bodyLineHeight,
    tracking:(prefs.spacing === "wide" ? .12 : f.bodyLetterSpacingEm)+"em",target:t.touch.minimumTargetPx+"px",
    radius:t.radiusPx.control+"px"
  };
}

export function validBoard(board) {
  return typeof board?.title === "string" && board.title.length <= 72 &&
    Array.isArray(board.rows) && board.rows.length <= 8 && board.rows.every(row =>
      row && ["note","task","option"].includes(row.kind) && typeof row.label === "string" &&
      row.label.length <= 80 && (row.detail === undefined || typeof row.detail === "string" && row.detail.length <= 140));
}

export function readableCanvas(html,t,large,prefs) {
  const v = displayVars(t,large,prefs);
  const fonts = ["next","mono"].map((family,i) => {
    const url = new URL("atkinsonhyperlegible"+family+".ttf",location.href);
    return '@font-face{font-family:"'+[t.font.ui[0],t.font.mono[0]][i]+'";src:url("'+url+'");font-weight:100 900;font-display:swap}';
  }).join("");
  const style = fonts+'html{color-scheme:light}body{font:'+v["body-size"]+'/'+v.leading+' '+v.ui+
    ';color:'+v.ink+';background:'+v.paper+';letter-spacing:'+v.tracking+'}button,input,select,textarea{font:inherit;max-width:100%}pre,code{font-family:'+v.mono+
    ';white-space:pre-wrap;overflow-wrap:anywhere}table,math[display=block]{max-width:100%;overflow:auto;display:block}';
  return html.replace("<!--me3-reading-style-->",() => "<style>"+style+"</style>")
    .replace("font-src 'none'",()=>"font-src "+location.origin);
}
