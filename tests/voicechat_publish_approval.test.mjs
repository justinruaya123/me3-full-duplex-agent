import assert from "node:assert/strict";
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {setTimeout as delay} from "node:timers/promises";
import test from "node:test";
import {confirmPublication} from "../integrations/voicechat/publish_approval.mjs";

const title = "Publish to GitHub Pages?";
const detail = "Publish revision 2 to github.com/octo/harbor?\nindex.html";
function fixture(t) {
  const folder = mkdtempSync(join(tmpdir(), "me3-approval-"));
  process.env.ME3_WINDOW_DIR = folder;
  t.after(() => {
    delete process.env.ME3_WINDOW_DIR;
    rmSync(folder, {recursive:true,force:true});
  });
  const ctl = new AbortController();
  const ask = options => confirmPublication(detail, {
    signal:ctl.signal, current:() => !ctl.signal.aborted, timeout:1000,
    confirm:() => assert.fail("window must not prompt in Pi"), ...options,
  });
  const pending = () => JSON.parse(readFileSync(join(folder,"publication.json"), "utf8"));
  const respond = (id, approved) => writeFileSync(join(folder,"publication-response.json"), JSON.stringify({id,approved}));
  return {ask,pending,respond,ctl};
}

test("window publishes only a fresh exact browser decision, then clears the dialog", async t => {
  const f = fixture(t);
  const first = f.ask();
  const request = f.pending();
  assert.deepEqual({title:request.title,detail:request.detail}, {title,detail});
  f.respond(request.id, false);
  assert.equal(await first, false);
  assert.equal(f.pending(), null);
  const second = f.ask();
  const next = f.pending();
  assert.notEqual(next.id, request.id);
  f.respond(request.id, true);
  assert.equal(await Promise.race([second,delay(100,"pending")]), "pending");
  f.respond(next.id, true);
  assert.equal(await second, true);
  assert.equal(f.pending(), null);
});

test("window expiry and cancelled or superseded turns fail closed and clear approval", async t => {
  const f = fixture(t);
  assert.equal(await f.ask({timeout:20}), false);
  assert.equal(f.pending(), null);
  let current = true;
  const pending = f.ask({current:() => current});
  f.respond(f.pending().id, true);
  current = false;
  assert.equal(await pending, false);
  assert.equal(f.pending(), null);
  const aborted = f.ask();
  f.respond(f.pending().id, true);
  f.ctl.abort();
  assert.equal(await aborted, false);
  assert.equal(f.pending(), null);
});

test("terminal-only approval uses the interactive Pi confirm", async () => {
  const {signal} = new AbortController();
  const confirm = (...args) => {
    assert.deepEqual(args, [title,detail,{signal,timeout:60000}]);
    return true;
  };
  assert.equal(await confirmPublication(detail,{confirm,signal,current:() => true}), true);
});
