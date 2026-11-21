import assert from "node:assert/strict";
import {mkdtemp, realpath, readFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";

test("a transferred checkout trusts only itself in the BMO profile and honors an explicit denial", async t => {
  const {prepareTrust} = await import("../integrations/voicechat/project.mjs");
  const {mkdir,rm,writeFile} = await import("node:fs/promises");
  const base=await realpath(await mkdtemp(join(tmpdir(),"me3-trust-")));
  t.after(() => rm(base,{recursive:true,force:true}));
  const root=join(base,"transferred"), profile=join(root,".local/pi");
  await mkdir(profile,{recursive:true});
  prepareTrust(root,profile);
  const file=join(profile,"trust.json");
  assert.deepEqual(JSON.parse(await readFile(file)),{[root]:true});
  await writeFile(file,JSON.stringify({[root]:false}));
  assert.throws(() => prepareTrust(root,profile), /trust-project/);
  prepareTrust(root,profile,true);
  assert.deepEqual(JSON.parse(await readFile(file)),{[root]:true});
});

test("subagents receive the named role and selected repository workflow", async () => {
  const {subagentBrief} = await import("../integrations/voicechat/subagents.mjs");
  const brief=await subagentBrief("reviewer","Check this proposed approach.","systematic-debugging");
  assert.match(brief,/reviewer/i);
  assert.match(brief,/Root Cause Investigation/i);
  assert.ok(brief.includes("Check this proposed approach."));
  await assert.rejects(subagentBrief("reviewer","Review it","../../private"));
});

test("development assignments default to systematic debugging only when no workflow was selected", async () => {
  const {subagentRequest, subagentBrief, subagentPrefix} = await import("../integrations/voicechat/subagents.mjs");
  const assignment = (task, skill, development) => JSON.parse(
    subagentRequest("reviewer", task, skill, {development}).slice(subagentPrefix.length));
  const selected = assignment("Deepgram crashed after the second turn.", undefined, true);
  assert.equal(selected.skill, "systematic-debugging");
  assert.match(await subagentBrief(selected.agent, selected.task, selected.skill), /Root Cause Investigation/i);
  assert.equal(assignment("Review this packing checklist.").skill, undefined);
  assert.equal(assignment("Plan a migration.", "writing-plans", true).skill, "writing-plans");
  assert.throws(() => assignment("Review it", "../../private", true), /Unknown/);
});
