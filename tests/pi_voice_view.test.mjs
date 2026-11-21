import assert from "node:assert/strict";
import test from "node:test";
import { voiceWidget } from "../me3/pi_voice_view.mjs";

test("rolling ASR, interrupted speech and fresh sessions in the Pi widget", () => {
  let lines, footer;
  const observe = voiceWidget(value => { lines = value; }, value => { footer = value; });
  const send = (kind, fields = {}) => observe({kind, session_id:"a", ...fields});
  send("voice_open");
  send("asr_partial", {turn_id:"1", revision:1, text:"forty"});
  send("asr_partial", {turn_id:"1", revision:2, text:"four teas"});
  send("mic_level", {peak:16384});
  assert.match(footer, /Mic.*−6 dBFS.*four teas/);
  assert.deepEqual(lines, []);
  send("asr_final", {turn_id:"1", revision:3, text:"four trees"});
  send("speech_script", {utterance:"u1", text:"Oak and ash."});
  send("speech_audio", {utterance:"u1"});
  send("asr_partial", {turn_id:"2", revision:1, text:"actually"});
  assert.deepEqual(lines, ["You  four trees", "ME3 · audio started  Oak and ash."]);
  send("speech_interrupted", {utterance:"u1"});
  send("speech_complete", {utterance:"old"});
  assert.equal(lines[1], "ME3 · interrupted  Oak and ash.");
  send("asr_final", {turn_id:"2", revision:2, text:"actually, one tree"});
  send("asr_partial", {turn_id:"2", revision:1, text:"stale"});
  assert.equal(lines.at(-1), "You  actually, one tree");
  assert.doesNotMatch(footer, /actually|stale/);
  send("voice_closed");
  send("speech_audio", {utterance:"u1"});
  assert.equal(lines, undefined);
  send("mic_level", {peak:32768});
  assert.equal(footer, undefined);
  send("voice_open", {session_id:"b"});
  send("asr_final", {turn_id:"2", revision:10, text:"previous session"});
  assert.deepEqual(lines, []);
});

test("script companion output is visible alongside its utterance", () => {
  let lines;
  const observe = voiceWidget(value => { lines = value; });
  observe({kind:"voice_open", session_id:"s"});
  observe({kind:"companion", session_id:"s", text:"Source: https://example.org/weather"});
  assert.deepEqual(lines, ["ME3 · details  Source: https://example.org/weather"]);
});

test("silence, full scale and unchanged peaks only update the microphone row", () => {
  const transcript = [], mic = [];
  const observe = voiceWidget(lines => transcript.push(lines), line => mic.push(line));
  const send = (kind, fields = {}) => observe({kind, session_id:"live", ...fields});
  send("voice_open");
  assert.equal(mic.at(-1), "Mic · waiting for input");
  send("mic_level", {peak:0});
  send("mic_level", {peak:0});
  send("mic_level", {peak:32768});
  assert.deepEqual(mic.slice(1), ["Mic ░░░░░░░░░░ −∞ dBFS", "Mic ██████████ 0 dBFS"]);
  assert.deepEqual(transcript, [[]]);
});
