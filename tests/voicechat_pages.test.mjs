import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdir, mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {publishPages} from "../integrations/voicechat/pages.mjs";

const args = {job:"a".repeat(32), revision:2, repo:"octo/harbor"};
const source = {branch:"bmo-pages", path:"/"};
const tree = "b".repeat(40), commit = "c".repeat(40), old = "d".repeat(40);

async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), "bmo-publish-"));
  t.after(() => rm(dir, {recursive:true, force:true}));
  await mkdir(join(dir,"site/assets"), {recursive:true});
  const files = {"index.html":"<h1>Harbor</h1>", "assets/app.css":"h1 { color: navy }"};
  const sha256 = {};
  for (const [name, content] of Object.entries(files)) {
    sha256[name] = createHash("sha256").update(content).digest("hex");
    await writeFile(join(dir,"site",name), content);
  }
  await writeFile(join(dir,"site","private.txt"), "excluded from verification");
  const receipt = join(dir,"verification.json");
  await writeFile(receipt, JSON.stringify({kind:"trusted-static-build", passed:true, job_id:args.job, revision:2, sha256}));
  const job = {id:args.job, status:"completed", kind:"website", revision:2, receipt};
  const calls = [], dialogs = [];
  const state = {head:null, pages:null, current:true};
  const options = {
    request:"Push this site to GitHub Pages for octo/harbor.",
    current:() => state.current,
    getJob:async id => id === job.id && job,
    confirm:async detail => {dialogs.push(detail); return true;},
    api:async (method, endpoint, body) => {
      assert.ok(endpoint.startsWith("repos/octo/harbor/"));
      const op = endpoint.slice("repos/octo/harbor/".length);
      calls.push({method, op, body});
      if (method === "GET") {
        if (op === "git/ref/heads/bmo-pages" && state.head) return {object:{sha:state.head}};
        if (op === "git/commits/"+state.head) return {tree:{sha:state.tree}};
        if (op === "pages" && state.pages) return state.pages;
        throw Object.assign(Error("Missing"), {httpStatus:404});
      }
      if (op === "git/trees") return {sha:tree};
      if (op === "git/commits") return {sha:commit};
      if (op.startsWith("git/refs")) {
        state.head = body.sha;
        state.tree = tree;
      } else if (op === "pages") {
        if (state.failPages) throw Error("Pages permission denied");
        state.pages = {build_type:"legacy",source:body.source};
      } else assert.fail("unexpected API write: "+op);
      return {};
    },
  };
  return {state, job, options, calls, dialogs, files, dir, publish:() => publishPages(args, options)};
}

test("publish the approved verified site and retry without a duplicate commit", async t => {
  const f = await fixture(t);
  const result = await f.publish();
  assert.match(result, /octo\/harbor/);
  assert.match(result, /bmo-pages/);
  assert.match(result, /deployment.*unverified|deployment.*pending/i);
  assert.match(f.dialogs[0], /assets\/app.css/);
  assert.match(f.dialogs[0], /octo\/harbor/);
  const upload = f.calls.find(c => c.op === "git/trees").body.tree;
  assert.deepEqual(Object.fromEntries(upload.map(e => [e.path,e.content])), {...f.files,".nojekyll":""});
  assert.deepEqual(f.calls.find(c => c.op === "git/refs").body, {ref:"refs/heads/bmo-pages", sha:commit});
  assert.deepEqual(f.state.pages.source, source);
  await f.publish();
  assert.equal(f.calls.filter(c => c.op === "git/commits" && c.method === "POST").length, 1);
  assert.equal(f.calls.filter(c => c.op === "pages" && c.method !== "GET").length, 1);
});

test("update is a fast-forward and a Pages failure reports the commit already pushed", async t => {
  const f = await fixture(t);
  Object.assign(f.state, {head:old, tree:old, failPages:true});
  await assert.rejects(f.publish(), /pushed.*Pages permission denied/i);
  assert.deepEqual(f.calls.find(c => c.op === "git/commits").body.parents,[old]);
  assert.deepEqual(f.calls.find(c => c.method === "PATCH").body, {sha:commit, force:false});
});

test("explanations, declined approval, changed turn or revision and modified files cannot upload", async t => {
  const f = await fixture(t);
  for (const request of ["How do I push to GitHub Pages?", "Do not publish this to GitHub Pages", "Build a website"]) {
    await assert.rejects(publishPages(args,{...f.options, request}));
  }
  assert.equal(f.dialogs.length, 0);
  await assert.rejects(publishPages(args,{...f.options,confirm:async () => false}), /approv|declin/i);
  await assert.rejects(publishPages(args,{...f.options,confirm:async () => {
    f.state.current = false; return true;
  }}), /current|changed|expired/i);
  f.state.current = true;
  await assert.rejects(publishPages(args,{...f.options,confirm:async () => {
    f.job.revision++; return true;
  }}), /revision/i);
  f.job.revision = 2;
  await writeFile(join(f.dir,"site/index.html"),"changed");
  await assert.rejects(f.publish(), /verif|changed/i);
  assert.equal(f.calls.filter(c => c.method !== "GET").length,0);
});
