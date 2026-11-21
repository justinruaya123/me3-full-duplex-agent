// Only the interactive client can publish. Workers return static files as data.
import {createHash} from "node:crypto";
import {readFile, realpath, stat} from "node:fs/promises";
import {dirname, join} from "node:path";
import {requestsGitHubAction, runCommand} from "../../me3/pi_github.mjs";

const branch = "bmo-pages";
const source = {branch, path:"/"};

function requestsPages(text) {
  const request = text.trim().replace(/^(?:hey[, ]+)?bmo[, ]+/i, "")
    .replace(/^(?:can|could|would) we /i, "");
  return /\bgithub\s+pages\b/i.test(request) &&
    (requestsGitHubAction(request, "pages") || requestsGitHubAction(request, "push"));
}

async function verifiedTree(job) {
  const receipt = JSON.parse(await readFile(job.receipt, "utf8"));
  if (receipt.kind !== "trusted-static-build" || receipt.passed !== true ||
      receipt.job_id !== job.id || receipt.revision !== job.revision)
    throw Error("Website verification does not match the requested job revision.");
  const hashes = Object.entries(receipt.sha256 ?? {});
  if (!Object.hasOwn(receipt.sha256 ?? {}, "index.html") || hashes.length > 32)
    throw Error("The verified website manifest is incomplete.");
  const dir = await realpath(join(dirname(job.receipt), "site"));
  const tree = [{path:".nojekyll", type:"blob", mode:"100644", content:""}];
  let size = 0;
  for (const [name, digest] of hashes) {
    if (name.length > 128 || /[\\\p{C}]/u.test(name) ||
        name.split("/").some(part => !part || part.startsWith(".")))
      throw Error("Invalid path in website receipt.");
    const path = join(dir, name);
    if (await realpath(path) !== path) throw Error("The verified website path changed.");
    const file = await stat(path);
    size += file.size;
    if (!file.isFile() || size > 2_097_152) throw Error("Invalid verified website file or size.");
    const data = await readFile(path);
    if (createHash("sha256").update(data).digest("hex") !== digest)
      throw Error("Website changed after verification. Build a fresh revision.");
    tree.push({path:name, type:"blob", mode:"100644", content:data.toString("utf8")});
  }
  return tree;
}

async function ghApi(method, endpoint, body, signal) {
  const args = ["api", "--hostname", "github.com", "--method", method, endpoint];
  if (body) args.push("--input", "-");
  if (method === "POST" && /\/git\/(?:trees|commits)$/.test(endpoint))
    args.push("--jq", "{sha: .sha}"); // A recursive tree response can exceed the CLI output bound.
  const env = {GH_PROMPT_DISABLED:"1"};
  for (const key of ["HOME","PATH","TMPDIR","GH_CONFIG_DIR","XDG_CONFIG_HOME","GITHUB_TOKEN","GH_TOKEN"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  let result;
  try {
    result = await runCommand("gh", args, {env, signal, input:body && JSON.stringify(body)});
  } catch (err) {
    if (err.code === "ENOENT") throw Error("Install GitHub CLI and sign in with gh auth login.");
    throw err;
  }
  return result ? JSON.parse(result) : {};
}

export async function publishPages({job, revision, repo}, {request, current, getJob, confirm, signal, api = ghApi}) {
  if (!requestsPages(request)) throw Error("Ask to publish this site to GitHub Pages first.");
  if (!/^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?\/[a-z\d_-][a-z\d._-]{0,99}$/i.test(repo) ||
      /\.git$|\.$/i.test(repo)) throw Error("Specify the GitHub repository as OWNER/REPO.");
  async function checkRevision() {
    if (!current()) throw Error("The publishing request expired.");
    const record = await getJob(job);
    if (!current()) throw Error("The publishing request expired.");
    if (!record || record.id !== job || record.kind !== "website" || record.status !== "completed" ||
        record.revision !== revision || !record.receipt)
      throw Error("Select a completed website and its current verified revision in this chat.");
    return record;
  }
  const tree = await verifiedTree(await checkRevision());
  const manifest = tree.map(file => file.path).join("\n");
  if (!current()) throw Error("The publishing request expired.");
  const approved = await confirm(`Publish website ${job}, revision ${revision}, to github.com/${repo}?\n` +
    `This uploads these files, replaces the contents of branch ${branch}, and sets the public Pages source to its root:\n${manifest}`);
  if (approved !== true) throw Error("GitHub Pages publication declined.");

  const call = async (method, path, body) => {
    await checkRevision();
    return api(method, "repos/"+repo+"/"+path, body, signal);
  };
  async function optional(path) {
    try { return await call("GET", path); }
    catch (err) { if (err.httpStatus === 404) return null; throw err; }
  }
  const pages = await optional("pages");
  const ref = await optional("git/ref/heads/"+branch);
  const parent = ref?.object.sha;
  const previous = parent && await call("GET", "git/commits/"+parent);
  const snapshot = await call("POST", "git/trees", {tree});
  let sha = parent;
  if (!previous || previous.tree.sha !== snapshot.sha) {
    const commit = await call("POST", "git/commits", {
      message:`Publish BMO website ${job} revision ${revision}`,
      tree:snapshot.sha, parents:parent ? [parent] : [],
    });
    sha = commit.sha;
    if (parent) await call("PATCH", "git/refs/heads/"+branch, {sha, force:false});
    else await call("POST", "git/refs", {ref:"refs/heads/"+branch, sha});
  }
  const pushed = `Pushed ${repo} branch ${branch} at ${sha}.`;
  try {
    if (pages?.source?.branch !== branch || pages.source.path !== "/" || pages.build_type !== "legacy")
      await call(pages ? "PUT" : "POST", "pages", {build_type:"legacy", source});
  } catch (err) {
    throw Error(pushed + " Pages configuration was not confirmed. " + err.message);
  }
  return pushed + " GitHub Pages source configured. Live deployment is unverified.";
}
