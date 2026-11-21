#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
src="integrations/openintelligentui"
dest=".local/openintelligentui-renderer"
mkdir -p "$dest"
# CopilotKit/OpenIntelligentUI, commit 8391a94c1c3939c679e40ddd7bfc08a9ef690e70.
# Strip only TypeScript types, preserving the two upstream streaming functions.
node --disable-warning=ExperimentalWarning --input-type=module - "$src" "$dest" <<'NODE'
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
const [source, destination] = process.argv.slice(2);
const ts = readFileSync(source + "/process-partial-html.ts", "utf8");
if (createHash("sha256").update(ts).digest("hex") !== "6a5cf9f0ed122f690a77ca308df504098259d3177791e4048f820ec60e2d693b") {
  throw Error("OpenIntelligentUI source differs from the pinned renderer.");
}
writeFileSync(destination + "/process-partial-html.mjs", stripTypeScriptTypes(ts));
NODE
cp "$src/LICENSE" "$src/package.json" "$dest/"
if ! cmp -s "$src/package-lock.json" "$dest/package-lock.json" || ! (cd "$dest" && node -e 'require("parse5")') 2>/dev/null; then
  cp "$src/package-lock.json" "$dest/"
  npm ci --prefix "$dest" --ignore-scripts --no-audit --no-fund
fi
echo "OpenIntelligentUI streaming prototype renderer is ready."
