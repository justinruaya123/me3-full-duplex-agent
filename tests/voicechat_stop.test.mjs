import assert from "node:assert/strict";
import childProcess from "node:child_process";
import {EventEmitter} from "node:events";
import {registerHooks, syncBuiltinESMExports} from "node:module";
import {PassThrough} from "node:stream";
import test from "node:test";
// Pi supplies its extension dependencies from its own package tree.
const piPackage = new URL("../integrations/voicechat/node_modules/@earendil-works/pi-coding-agent/package.json", import.meta.url);
const aliases = registerHooks({resolve(name, context, next) {
  if (name === "@earendil-works/pi-tui" || name === "typebox")
    return next(name, {...context, parentURL:piPackage.href});
  return next(name, context);
}});
const {default:voicechat} = await import("../integrations/voicechat/pi.mjs");
aliases.deregister();

test("spoken stops are silent host controls and only a current live mic commit reaches jobs", async t => {
  process.env.ME3_CLIENT_HOME = "/unused";
  process.env.ME3_ASR_BACKEND = "deepgram";
  process.env.ME3_VOICE_TTS = "bmo";
  const deviceOps = [], jobOps = [], messages = [], handlers = new Map();
  let device;
  const spawn = t.mock.method(childProcess, "spawn", (_, args) => {
    const child = Object.assign(new EventEmitter(), {
      stdin:new PassThrough(), stdout:new PassThrough(), stderr:new PassThrough(),
    });
    const isDevice = args.includes("me3.parakeet_voice");
    if (isDevice) device = child;
    child.stdin.on("data", data => {
      const request = JSON.parse(data);
      (isDevice ? deviceOps : jobOps).push(request.op);
      if (!isDevice) child.stdout.write(JSON.stringify({id:request.id, result:{status:"empty"}}) + "\n");
    });
    child.stdin.on("end", () => child.emit("close", 0));
    return child;
  });
  syncBuiltinESMExports();
  t.after(() => {spawn.mock.restore(); syncBuiltinESMExports();});
  voicechat({
    on(name, handler) { handlers.set(name, handler); },
    getFlag:name => name === "voicechat-duplex", sendUserMessage:text => messages.push(text),
    registerTool() {}, registerFlag() {}, registerCommand() {}, appendEntry() {},
  });
  const context = {isIdle:() => true, sessionManager:{getSessionFile:() => undefined, getSessionId:() => "chat"},
    ui:{setStatus() {}, setWidget() {}, notify() {}}};
  handlers.get("session_start")({}, context);
  t.after(() => handlers.get("session_shutdown")());
  const send = (kind, fields) => device.stdout.write(JSON.stringify({kind, ...fields}) + "\n");
  const stop = (id, text, control, epoch) => {
    send("onset", {id});
    send("final", {id, text});
    send("commit", {id, text, control, epoch});
  };
  send("ready", {fixture:false, digital:false});
  stop("one", "Stop!", "stop_speech", 1);
  send("onset", {id:"two"});
  send("partial", {id:"two", text:"stop current task"});
  send("final", {id:"two", text:"stop talking"});
  send("commit", {id:"two", text:"stop current task", control:"stop_current_task", epoch:2});
  assert.deepEqual(jobOps, []);
  assert.deepEqual(messages, []);
  assert.ok(!deviceOps.includes("feedback") && !deviceOps.includes("say"));

  stop("three", "Stop current task.", "stop_current_task", 3);
  send("commit", {id:"three", text:"Stop current task.", control:"stop_current_task", epoch:3});
  assert.deepEqual(jobOps, ["cancel_current"]);
  for (const mode of [{fixture:true, digital:false}, {fixture:false, digital:true}]) {
    send("ready", mode);
    stop("recording", "Stop current task.", "stop_current_task", mode.fixture ? 4 : 5);
  }
  assert.deepEqual(jobOps, ["cancel_current"]);
  assert.deepEqual(messages, []);
  assert.ok(!deviceOps.includes("say"));
  stop("next", "What time is it?", undefined, 6);
  assert.deepEqual(messages, ["Microphone transcript: What time is it?"]);
});
