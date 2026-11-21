import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const defaults = fileURLToPath(new URL("./prompts/", import.meta.url));
const local = fileURLToPath(new URL("../../.local/voice-prompts/", import.meta.url));
const files = ["SYSTEM.md", "SOUL.md", "TOOLS.md", "USER.md", "USERS.md"];
const maxBytes = 8192;

function privateInstructions(content) {
  return content
    .replace(/^<!-- ME3 editing guide\r?\n[\s\S]*?-->/, "")
    .replace(/<!-- ME3 fields -->([\s\S]*?)<!-- \/ME3 fields -->/g, (_, rows) =>
      rows.split(/\r?\n/).filter(row =>
        row.trim() && !/^##\s/.test(row) && !/^\s*- [^:]+:\s*$/.test(row)
      ).join("\n")
    ).trim();
}

async function readSection(dir, name, optional) {
  const path = join(dir, name);
  try {
    const info = await stat(path);
    if (!info.isFile() || info.size > maxBytes)
      throw new Error(`Expected a Markdown file of at most ${maxBytes} bytes at ${path}`);
    const content = (await readFile(path, "utf8")).trim();
    return optional ? privateInstructions(content) : content;
  } catch (error) {
    if (optional && error.code === "ENOENT") return "";
    throw error;
  }
}

export async function composeVoicePrompt(base, dir = process.env.ME3_VOICE_PROMPT_DIR || local, {includeRemembered = true} = {}) {
  const sections = await Promise.all(files.map(async name => {
    // Older profiles may provide TOOLS.md. Pi supplies the tool descriptions.
    const shipped = ["SYSTEM.md", "SOUL.md"].includes(name) ? await readSection(defaults, name, false) : "";
    let extra = await readSection(dir, name, true);
    if (name === "USER.md" && !includeRemembered) {
      extra = extra.replace(/<!-- ME3 remembered -->[\s\S]*?<!-- \/ME3 remembered -->/g, "").trim();
    }
    const content = [shipped, extra].filter(Boolean).join("\n\n");
    return content && `## ${name}\n\n${content}`;
  }));
  return [base, ...sections].filter(Boolean).join("\n\n");
}

export async function composeWorkerPrompt(dir = process.env.ME3_VOICE_PROMPT_DIR || local, {website = false} = {}) {
  const base = await readSection(defaults, "WORKER.md", false);
  const extra = await readSection(dir, "WORKER.md", true);
  const sections = [base];
  if (website) {
    const skill = await readFile(new URL("./skills/bmo-frontend-design/SKILL.md", import.meta.url), "utf8");
    const tokens = JSON.parse(await readFile(new URL("./theme/design.tokens.json", import.meta.url), "utf8"));
    const {color, font, spacePx, radiusPx, focusRingPx, touch} = tokens;
    sections.push(skill.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "").trim(),
      "Default website tokens: " + JSON.stringify({color, font, spacePx, radiusPx, focusRingPx, touch}));
  }
  return [...sections, extra].filter(Boolean).join("\n\n");
}
