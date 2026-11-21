import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { composeVoicePrompt } from "../integrations/voicechat/prompts.mjs";

test("each Pi turn gets the current four sections, in order, alongside its original prompt", async t => {
  const dir = await mkdtemp(join(tmpdir(), "me3-prompt-"));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const files = ["SYSTEM.md", "SOUL.md", "TOOLS.md", "USER.md"];
  for (const name of files) await writeFile(join(dir, name), "custom-" + name);
  const first = await composeVoicePrompt("Pi base", dir);
  assert.ok(first.startsWith("Pi base"));
  assert.deepEqual(first.match(/custom-[A-Z]+\.md/g), files.map(name => "custom-" + name));
  assert.match(first, /Would you rather/);
  assert.doesNotMatch(first, /read_trial_brief|create_website|delegate_task|delegated_task_status/);
  await writeFile(join(dir, "USER.md"), "Call me Echo");
  const next = await composeVoicePrompt("Pi base", dir);
  assert.match(next, /Call me Echo/);
  assert.doesNotMatch(next, /custom-USER/);
  await rm(join(dir, "USER.md"));
  assert.doesNotMatch(await composeVoicePrompt("Pi base", dir), /Call me Echo/);
});

test("blank private notes add nothing and oversized instructions report the file", async t => {
  const dir = await mkdtemp(join(tmpdir(), "me3-prompt-"));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const base = await composeVoicePrompt("Pi base", dir);
  await writeFile(join(dir, "USER.md"), "  \n");
  assert.equal(await composeVoicePrompt("Pi base", dir), base);
  await writeFile(join(dir, "USER.md"), "x".repeat(8193));
  await assert.rejects(composeVoicePrompt("Pi base", dir), /USER.md/);
});

test("worker loads only WORKER.md and receives only its configured credential", async t => {
  const {composeWorkerPrompt} = await import("../integrations/voicechat/prompts.mjs");
  const {workerEnv} = await import("../integrations/voicechat/jobs.mjs");
  const dir = await mkdtemp(join(tmpdir(), "me3-worker-"));
  t.after(() => rm(dir, {recursive:true, force:true}));
  await writeFile(join(dir,"USER.md"), "private operator facts");
  await writeFile(join(dir,"WORKER.md"), "Give the handback in two paragraphs.");
  const worker = await composeWorkerPrompt(dir);
  assert.match(worker, /two paragraphs/);
  assert.doesNotMatch(worker, /private operator facts/);
  const env = workerEnv({ME3_ASR_TOKEN:"private", ME3_WORKER_API_KEY_ENV:"TEST_KEY",
    TEST_KEY:"worker", PI_CODING_AGENT_DIR:"system"}, "/project");
  assert.equal(env.ME3_PROJECT_AUTH_DIR, "/project/.local/pi");
  assert.equal(env.TEST_KEY, "worker");
  assert.equal(env.ME3_ASR_TOKEN, undefined);
  assert.equal(env.PI_CODING_AGENT_DIR, undefined);
});

test("untouched editing guides add no model context and only the requested role gets edits", async t => {
  const {readFile} = await import("node:fs/promises");
  const {composeWorkerPrompt} = await import("../integrations/voicechat/prompts.mjs");
  const dir = await mkdtemp(join(tmpdir(), "me3-new-profile-"));
  t.after(() => rm(dir, {recursive:true, force:true}));
  const foreground = await composeVoicePrompt("Pi base", dir);
  assert.doesNotMatch(foreground, /## TOOLS\.md/);
  const worker = await composeWorkerPrompt(dir);
  for (const name of ["SYSTEM", "SOUL", "USER", "WORKER"]) {
    const template = new URL(`../integrations/voicechat/templates/${name}.md`, import.meta.url);
    await writeFile(join(dir, name + ".md"), await readFile(template));
  }
  assert.equal(await composeVoicePrompt("Pi base", dir), foreground);
  assert.equal(await composeWorkerPrompt(dir), worker);
  const user = join(dir, "USER.md");
  await writeFile(user, (await readFile(user, "utf8")) + "\nCall me Juniper.\n");
  assert.match(await composeVoicePrompt("Pi base", dir), /Call me Juniper/);
  assert.equal(await composeWorkerPrompt(dir), worker);
});

test("fillable fields keep supplied values, omit blank rows, and preserve free-form notes", async t => {
  const {readFile} = await import("node:fs/promises");
  const {composeWorkerPrompt} = await import("../integrations/voicechat/prompts.mjs");
  const dir = await mkdtemp(join(tmpdir(), "me3-fields-"));
  t.after(() => rm(dir, {recursive:true, force:true}));
  const user = await readFile(new URL("../integrations/voicechat/templates/USER.md", import.meta.url), "utf8");
  assert.ok(user.includes("- Preferred name:"));
  await writeFile(join(dir, "USER.md"), user.replace("- Preferred name:", "- Preferred name: Jo")
    .replace("- Time zone:", "- Time zone: UTC+05:30").replaceAll("\n", "\r\n") + "\nAn extra note.");
  const prompt = await composeVoicePrompt("base", dir);
  assert.match(prompt, /Preferred name: Jo/);
  assert.match(prompt, /Time zone: UTC\+05:30/);
  assert.match(prompt, /An extra note\./);
  assert.doesNotMatch(prompt, /City or region:|ME3 fields/);
  assert.doesNotMatch(await composeWorkerPrompt(dir), /Preferred name: Jo/);
  const freeform = "Agenda:\n- Notes:\n# My heading\nUse these topics.";
  await writeFile(join(dir, "USER.md"), freeform);
  assert.ok((await composeVoicePrompt("base",dir)).endsWith(freeform));
});

test("a private USERS.md supplement reaches the foreground alongside USER.md", async t => {
  const dir = await mkdtemp(join(tmpdir(), "me3-owner-"));
  t.after(() => rm(dir,{recursive:true,force:true}));
  await writeFile(join(dir,"USER.md"),"Prefers short replies.");
  await writeFile(join(dir,"USERS.md"),"My full name is Tess Example.");
  const prompt = await composeVoicePrompt("base",dir);
  assert.match(prompt,/Tess Example/);
  assert.match(prompt,/Prefers short replies/);
});

test("only website workers get the project design skill and current design tokens", async () => {
  const {composeWorkerPrompt} = await import("../integrations/voicechat/prompts.mjs");
  const {readFile} = await import("node:fs/promises");
  const tokens = JSON.parse(await readFile(new URL("../integrations/voicechat/theme/design.tokens.json", import.meta.url)));
  const site = await composeWorkerPrompt(undefined, {website:true});
  const skill = await readFile(new URL("../integrations/voicechat/skills/bmo-frontend-design/SKILL.md", import.meta.url), "utf8");
  const guidelines = skill.slice(skill.indexOf("\n---\n", 4) + 5).trim();
  assert.ok(site.includes(guidelines));
  assert.ok(!(await composeWorkerPrompt()).includes(guidelines));
  assert.ok(site.includes(tokens.color.paper));
  assert.ok(site.includes(tokens.font.ui[0]));
  assert.ok(!site.includes("schemaVersion"));
  assert.ok(!(await composeWorkerPrompt()).includes(tokens.color.paper));
});
