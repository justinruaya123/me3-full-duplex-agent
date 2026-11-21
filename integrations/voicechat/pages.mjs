// Client-only publication. Workers cannot choose an account or execute Git.
import {createHash} from "node:crypto";
import {mkdir, mkdtemp, readFile, realpath, rm, stat, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {dirname, join} from "node:path";
import {runCommand} from "../../me3/pi_github.mjs";

const branch = "bmo-pages", ref = `refs/heads/${branch}`;
const owner = /^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?$/i;
const repository = /^[a-z\d_-][a-z\d._-]{0,99}$/i;
function checkRepo(repo) {
  const [a,b,...rest] = String(repo).split("/");
  if (!owner.test(a) || !b || rest.length || !repository.test(b) || /\.git$|\.$/i.test(b))
    throw Error("Specify the GitHub repository as OWNER/REPO.");
}

// Match an immediate instruction in the committed turn, not a model-selected
// target, old approval, hypothetical, question about Git, or compound request.
function operatorIntent(request, repo) {
  const text = request.trim().replace(/^(?:hey[, ]+)?bmo[, ]+/i, "");
  const m = /^(?:(?:can|could|would) (?:you|we) )?(?:please )?(?:git )?(push|publish|deploy)\s+(?:(?:it|(?:this|the|my)(?: (?:verified |finished |completed )?(?:site|website|page))?)\s+)?(?:(?:in)?to\s+)?(?:(?:a new )?github(?: (pages?))?(?: (?:for|to|at|in))?\s+)?(?:https:\/\/github\.com\/)?([\w-]+\/[\w.-]+?)[.!?]?$/i.exec(text);
  if (!m || m[3].toLowerCase() !== repo.toLowerCase())
    throw Error('Name the repository in the current push request, e.g. "Push this site to GitHub for OWNER/REPO."');
  return {pages:!!m[2] || m[1].toLowerCase() !== "push"};
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
  const tree = [{path:".nojekyll",content:""}];
  let size = 0;
  for (const [name,digest] of hashes) {
    if (name.length > 128 || /[\\\p{C}]/u.test(name) || name.split("/").some(p => !p || p.startsWith(".")))
      throw Error("Invalid path in website receipt.");
    const path = join(dir,name);
    if (await realpath(path) !== path) throw Error("The verified website path changed.");
    const file = await stat(path);
    size += file.size;
    if (!file.isFile() || size > 2_097_152) throw Error("Invalid verified website file or size.");
    const data = await readFile(path);
    if (createHash("sha256").update(data).digest("hex") !== digest)
      throw Error("Website changed after verification. Build a fresh revision.");
    tree.push({path:name,content:data});
  }
  return tree;
}

function githubEnv() {
  const env = {GH_PROMPT_DISABLED:"1",GIT_TERMINAL_PROMPT:"0",GIT_CONFIG_NOSYSTEM:"1",
    GIT_CONFIG_GLOBAL:"/dev/null",GIT_ATTR_NOSYSTEM:"1",GIT_ALLOW_PROTOCOL:"https"};
  for (const key of ["HOME","PATH","TMPDIR","GH_CONFIG_DIR","XDG_CONFIG_HOME","GH_TOKEN","GITHUB_TOKEN"])
    if (process.env[key]) env[key] = process.env[key];
  return env;
}
async function ghApi(method, endpoint, body, signal) {
  const args = ["api","--hostname","github.com","--method",method,endpoint];
  if (body) args.push("--input","-");
  try {
    const text = await runCommand("gh",args,{env:githubEnv(),signal,input:body && JSON.stringify(body)});
    return text ? JSON.parse(text) : {};
  } catch (err) {
    if (err.code === "ENOENT") throw Error("Install GitHub CLI and sign in with gh auth login.");
    throw err;
  }
}

// Build an index from verified bytes in an empty worktree. Never check out
// remote files (including hooks/attributes), add the project, or force a ref.
export async function pushVerifiedFiles({repo,tree,job,revision},{check,signal,runner=runCommand}) {
  checkRepo(repo);
  const cwd = await mkdtemp(join(tmpdir(),"me3-pages-"));
  const url = `https://github.com/${repo}.git`;
  const config = ["core.hooksPath=/dev/null","credential.helper=",
    "credential.https://github.com.helper=!gh auth git-credential","http.followRedirects=false",
    "core.autocrlf=false","core.attributesFile=/dev/null","core.excludesFile=/dev/null","user.name=BMO","user.email=bmo@localhost"]
    .flatMap(setting => ["-c",setting]);
  const git = (...args) => runner("git",[...config,...args],{cwd,signal,env:githubEnv()});
  try {
    await git("init","--quiet","--template=");
    for (const file of tree) {
      const path = join(cwd,file.path);
      await mkdir(dirname(path),{recursive:true});
      await writeFile(path,file.content,{flag:"wx"});
    }
    await git("--literal-pathspecs","add","--",...tree.map(file=>file.path));
    const snapshot = await git("write-tree");
    await check();
    const existing = await git("ls-remote","--refs",url,ref);
    let parent;
    if (existing) {
      await git("fetch","--quiet","--depth=1","--no-tags",url,ref);
      parent = await git("rev-parse","--verify","FETCH_HEAD^{commit}");
      if (await git("rev-parse","FETCH_HEAD^{tree}") === snapshot) {
        await check();
        return parent;
      }
    }
    const sha = await git("commit-tree",snapshot,...(parent ? ["-p",parent] : []),"-m",
      `Publish BMO website ${job} revision ${revision}`);
    await check();
    await git("push","--porcelain",url,`${sha}:${ref}`);
    return sha;
  } finally { await rm(cwd,{recursive:true,force:true}); }
}

async function account(api, signal) {
  const user = await api("GET","user",undefined,signal);
  if (!user?.login || !owner.test(user.login)) throw Error("Sign in to github.com with gh auth login.");
  return user.login;
}

export async function publishLatestSite(target, opts) {
  if (!opts.current()) throw Error("The publishing request expired.");
  if (typeof target !== "string" || !target) throw Error("Use an existing REPO or OWNER/REPO.");
  if (target.includes("/")) checkRepo(target);
  else if (!repository.test(target) || /\.git$|\.$/i.test(target)) throw Error("Use an existing REPO or OWNER/REPO.");
  const repo = target.includes("/") ? target : `${await account(opts.api ?? ghApi,opts.signal)}/${target}`;
  const record = await opts.getLatest();
  if (!record?.id) throw Error("There is no website in this chat. Resume the Pi chat where the site was built.");
  if (record.status !== "completed") throw Error(`The latest website is not completed (${record.status}).`);
  return publishPages({job:record.id,revision:record.revision,repo},{...opts,
    request:`${opts.pages === false ? "Push" : "Publish"} this site to GitHub for ${repo}`});
}

export async function publishPages({job,revision,repo},{request,current,getLatest,getJob,signal,api=ghApi,push=pushVerifiedFiles}) {
  checkRepo(repo);
  const {pages} = operatorIntent(request,repo);
  async function check() {
    if (!current()) throw Error("The publishing request expired.");
    const latest = await getLatest();
    if (latest?.id !== job) throw Error("Only the latest website in this chat may be pushed by this request.");
    const record = await getJob(job);
    if (!current()) throw Error("The publishing request expired.");
    if (record?.id !== job || record.kind !== "website" || record.status !== "completed" || record.revision !== revision || !record.receipt)
      throw Error("Select a completed website and its current verified revision in this chat.");
    return record;
  }
  const tree = await verifiedTree(await check());
  const login = await account(api,signal);
  if (repo.split("/")[0].toLowerCase() !== login.toLowerCase()) throw Error(`Choose a repository owned by the signed-in GitHub account (${login}).`);
  const base = "repos/"+repo;
  const info = await api("GET",base,undefined,signal);
  if (info?.full_name?.toLowerCase() !== repo.toLowerCase() || info.permissions?.push !== true || info.archived)
    throw Error("The repository must exist under the signed-in account and be writable.");
  await check();
  const sha = await push({repo,tree,job,revision},{check,signal});
  const pushed = `Pushed ${repo} branch ${branch} at ${sha}.`;
  if (!pages) return pushed;
  try {
    await check();
    let prior;
    try { prior = await api("GET",base+"/pages",undefined,signal); }
    catch (err) { if (err.httpStatus !== 404) throw err; }
    if (prior?.source?.branch !== branch || prior.source.path !== "/" || prior.build_type !== "legacy") {
      await check();
      await api(prior ? "PUT" : "POST",base+"/pages",{build_type:"legacy",source:{branch,path:"/"}},signal);
    }
  } catch (err) { throw Error(pushed+" Pages configuration was not confirmed. "+err.message); }
  return pushed+" GitHub Pages source configured. Live deployment is unverified.";
}
