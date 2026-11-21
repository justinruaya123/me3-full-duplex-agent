import {readdirSync} from "node:fs";
import {readFile} from "node:fs/promises";

const skills = new URL("./vendor/superpowers/skills/", import.meta.url);
export const workflows = readdirSync(skills, {withFileTypes:true})
  .filter(entry => entry.isDirectory()).map(entry => entry.name).sort();
const roles = new Map([
  ["planner", "Develop a practical plan with dependencies and a way to verify the outcome."],
  ["reviewer", "Review the supplied material for concrete defects, risks, and missing evidence."],
  ["writer", "Produce the requested draft from the supplied material."],
]);
export const roleNames = [...roles.keys()];
export const subagentPrefix = "ME3_SUBAGENT_V1\n";

export function subagentRequest(agent, task, skill) {
  if (!roles.has(agent) || (skill !== undefined && !workflows.includes(skill)))
    throw Error("Unknown ME3 subagent or workflow.");
  if (typeof task !== "string" || !task.trim() || task.length > 12000)
    throw Error("The subagent needs a task of up to 12000 characters.");
  return subagentPrefix + JSON.stringify({agent,task,skill});
}

export async function subagentBrief(agent, task, skill) {
  subagentRequest(agent, task, skill);
  const guide = skill ? await readFile(new URL(skill + "/SKILL.md", skills), "utf8") : "";
  return [`You are the project’s ${agent} subagent. ${roles.get(agent)}`,
    "Work from the supplied material. Report missing evidence and use only tools the host provides.",
    guide, "Assignment:\n" + task].filter(Boolean).join("\n\n");
}
