import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync, rmSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import {LiveBenchmark} from "../integrations/voicechat/live-benchmark.mjs";
import nitro, {routeNitro} from "../integrations/voicechat/nitro.mjs";

test("only a matching first output counts; missed replies stay in the denominator", t => {
  const root = mkdtempSync(join(tmpdir(), "me3-bench-"));
  t.after(() => rmSync(root, {force:true, recursive:true}));
  const bench = new LiveBenchmark(root);
  for (const id of ["one", "two"]) bench.command(id, {vad_end:10, final_at:10.2, text:id});
  assert.equal(bench.output({receipt:"old", first_output:15}), undefined);
  const e = {receipt:"two", first_output:11.5, tts_start:11};
  assert.match(bench.output(e), /1500 ms/);
  assert.equal(bench.output(e), undefined);
  bench.rate(4, "clear");
  assert.match(bench.summary(), /2 commands · 1 with audio · 1 without measured audio.*4.0\/5/);
});

test("GPT-OSS Nitro requests carry the selected provider and retain tools", () => {
  let hook;
  nitro({on(event, fn) {assert.equal(event,"before_provider_request"); hook=fn;}});
  const payload = hook({payload:{model:"openai/gpt-oss-120b",tools:["lookup"]}});
  assert.equal(payload.model, "openai/gpt-oss-120b:nitro");
  assert.deepEqual(payload.provider.only, ["Cerebras"]);
  assert.equal(payload.provider.allow_fallbacks, false);
  assert.deepEqual(payload.tools, ["lookup"]);
});

test("spoken OpenRouter replies request a bounded completion and preserve smaller explicit limits", () => {
  let hook;
  nitro({on(_event,fn) {hook=fn;}});
  assert.equal(hook({payload:{max_tokens:40960}}).max_tokens,2048);
  assert.equal(hook({payload:{max_completion_tokens:512}}).max_completion_tokens,512);
});

test("worker drafts fit within a 4096-token output budget", () => {
  let hook;
  routeNitro({on(_event,fn) {hook=fn;}});
  assert.equal(hook({payload:{max_tokens:40960}}).max_tokens,4096);
});


test("live DeepSeek requests pin the dated Nitro snapshot and Nebius FP4", () => {
  let hook;
  routeNitro({on(_event, fn) {hook=fn;}});
  const result = hook({payload:{model:"deepseek/deepseek-v4.1-flash",
    reasoning:{effort:"high"},tools:["delegate"],stream:true,max_tokens:8192}});
  assert.equal(result.model,"deepseek/deepseek-v4.1-flash-20261017:nitro");
  assert.deepEqual(result.provider.only,["nebius/fp4"]);
  assert.equal(result.provider.allow_fallbacks,false);
  assert.equal(result.provider.require_parameters,true);
  assert.deepEqual(result.reasoning,{effort:"high"});
  assert.equal(result.stream,true);
  assert.deepEqual(result.tools,["delegate"]);
});

test("foreground thinking off is explicit on the DeepSeek wire and keeps tools", () => {
  let hook;
  nitro({on(_event, cb) { hook=cb; },getThinkingLevel:()=>"off"});
  const payload = hook({payload:{model:"deepseek/deepseek-v4.1-flash", tools:["lookup"]}});
  assert.deepEqual(payload.reasoning, {effort:"none"});
  assert.deepEqual(payload.tools, ["lookup"]);
});
