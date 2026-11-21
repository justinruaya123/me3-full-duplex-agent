import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdir, mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {runCommand} from "../me3/pi_github.mjs";
import {pushVerifiedFiles, publishLatestSite, publishPages} from "../integrations/voicechat/pages.mjs";

const args = {job:"a".repeat(32), revision:2, repo:"octo/harbor"};
async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), "bmo-git-"));
  t.after(() => rm(dir, {recursive:true,force:true}));
  await mkdir(join(dir,"site"));
  const content = "<h1>Harbor</h1>";
  await writeFile(join(dir,"site/index.html"),content);
  await writeFile(join(dir,"site/private.txt"),"not approved");
  const receipt = join(dir,"verification.json");
  await writeFile(receipt,JSON.stringify({kind:"trusted-static-build",passed:true,job_id:args.job,revision:2,
    sha256:{"index.html":createHash("sha256").update(content).digest("hex")}}));
  const job = {id:args.job,revision:2,kind:"website",status:"completed",receipt};
  const calls = [], pushes = [];
  const opts = {current:() => true,getLatest:async () => job,getJob:async () => job,
    request:"Push this site to GitHub for octo/harbor",confirm:() => assert.fail("unexpected approval"),
    api:async (method,path,body) => {
      calls.push([method,path,body]);
      if (path === "user") return {login:"octo"};
      if (path === "repos/octo/harbor") return {full_name:"octo/harbor",permissions:{push:true}};
      if (path.endsWith("/pages") && method === "GET") throw Object.assign(Error("missing"), {httpStatus:404});
      if (path.endsWith("/pages") && method === "POST") return {};
      assert.fail("unexpected API call");
    },push:async (data,{check}) => { await check(); pushes.push(data); return "b".repeat(40); }};
  return {dir,job,calls,pushes,opts};
}

test("account shorthand, real manifest, no confirmation, plain push leaves Pages untouched",async t => {
  const f = await fixture(t);
  const text = await publishLatestSite("harbor", {...f.opts,pages:false});
  assert.match(text,/Pushed octo\/harbor branch bmo-pages/);
  assert.deepEqual(f.pushes[0].tree.map(i=>i.path),[".nojekyll","index.html"]);
  assert.ok(f.calls.every(([method,path])=>method === "GET" && !path.endsWith("/pages")));
  assert.match(await publishPages(args,f.opts), /Pushed/);
});

test("only explicit Pages publication changes Pages, and reports partial success",async t => {
  const f = await fixture(t);
  const opts = {...f.opts,request:"Publish this site to GitHub Pages for octo/harbor"};
  assert.match(await publishPages(args,opts), /deployment is unverified/);
  assert.deepEqual(f.calls.at(-1),["POST","repos/octo/harbor/pages",{build_type:"legacy",source:{branch:"bmo-pages",path:"/"}}]);
  await assert.rejects(publishPages(args,{...opts,api:(method,...rest)=>{
    if (method === "POST") throw Error("Pages permission denied"); return opts.api(method,...rest);
  }}), /Pushed.*Pages permission denied/);
});

test("login alone, guesses, negations, hypothetical and foreign destinations never authorize push",async t => {
  const f = await fixture(t);
  for (const request of ["Approved.","Push it", "How do I push to GitHub Pages for octo/harbor?",
    "If tests pass, push to GitHub for octo/harbor", "Do not publish to GitHub Pages for octo/harbor",
    "Check the weather and push to octo/harbor", "Push it to GitHub for octo/other","Push to octo/harbor and octo/other"])
    await assert.rejects(publishPages(args,{...f.opts,request}));
  assert.deepEqual(f.calls,[]);
  for (const repo of ["other/harbor","../harbor","octo/.git","--all","https://elsewhere.invalid/x"]) {
    await assert.rejects(publishLatestSite(repo,f.opts));
  }
  for (const response of [undefined,{full_name:"octo/new-name",permissions:{push:true}},
    {full_name:"octo/harbor",permissions:{push:false}}]) {
    await assert.rejects(publishLatestSite("harbor",{...f.opts,api:async (_,path)=>{
      if (response === undefined) throw Error("Not logged in");
      return path === "user" ? {login:"octo"} : response;
    }}));
  }
  assert.equal(f.pushes.length,0);
});

test("stale revision and tampered build fail before a push",async t => {
  const f = await fixture(t);
  await assert.rejects(publishPages(args,{...f.opts,current:()=>false}), /expired/);
  await assert.rejects(publishPages(args,{...f.opts,getJob:()=>({...f.job,revision:3})}), /revision/);
  await assert.rejects(publishPages(args,{...f.opts,getLatest:()=>({...f.job,id:"d".repeat(32)})}), /latest website/);
  await writeFile(join(f.dir,"site/index.html"),"modified");
  await assert.rejects(publishPages(args,f.opts), /changed/i);
  assert.equal(f.pushes.length,0);
});

test("real git push: only verified files, fast-forward updates, no duplicate commits",async t => {
  const f = await fixture(t), remote = join(f.dir,"remote.git");
  const git = (args,cwd = f.dir) => runCommand("git",args,{cwd});
  await git(["init","--bare",remote]);
  const commands = [];
  const runner = (bin,args,opts) => {
    assert.equal(bin,"git"); commands.push(args);
    return runCommand(bin,args.map(x=>x === "https://github.com/octo/harbor.git" ? remote : x),
      {...opts,env:{...opts.env,GIT_ALLOW_PROTOCOL:"file"}});
  };
  const push = files => pushVerifiedFiles({...args,tree:Object.entries(files).map(([path,content])=>({path,content}))},
    {check:async()=>{},runner});
  const first = await push({"index.html":"one","assets/test.css":"p{}"});
  assert.equal(await push({"index.html":"one","assets/test.css":"p{}"}),first);
  const second = await push({"index.html":"two"});
  assert.notEqual(second,first);
  assert.equal(await git(["rev-parse","bmo-pages^"],remote),first);
  assert.equal(await git(["ls-tree","--name-only","bmo-pages"],remote),"index.html");
  assert.equal(commands.filter(a=>a.includes("push")).length,2);
  assert.ok(commands.every(a=>!a.includes("--force") && !a.includes("--force-with-lease")));
});
