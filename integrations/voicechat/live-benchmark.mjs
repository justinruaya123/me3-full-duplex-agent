import {nitroTarget} from "./nitro.mjs";
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

export class LiveBenchmark {
  constructor(root) {
    mkdirSync(root, {recursive:true, mode:0o700});
    this.file = join(root, randomUUID() + ".jsonl");
    this.turns = new Map();
    this.log("run", {asr:"deepgram/nova-3", ...nitroTarget(process.env.ME3_FOREGROUND_MODEL),
       tts:({bmo:"piper/bmo-v1.0-voice",kokoro:"kokoro"})[process.env.ME3_VOICE_TTS] || "piper/en_US-lessac-medium-int8", device:"CPU"});
  }
  log(event, data) {
    appendFileSync(this.file, JSON.stringify({event, at:new Date().toISOString(), ...data}) + "\n", {mode:0o600});
  }
  command(id, event) {
    this.last = id;
    this.turns.set(id, {vadEnd:event.vad_end, deviceCommit:event.final_at, commit:performance.now()});
    this.log("command", {id, transcript:event.text, vadToCommitMs:Math.round(1000*(event.final_at-event.vad_end))});
  }
  firstText(id) {
    const turn = this.turns.get(id);
    if (!turn || turn.firstTextMs !== undefined) return;
    turn.firstTextMs = Math.round(performance.now() - turn.commit);
    this.log("first_model_text", {id, commitToFirstTextMs:turn.firstTextMs});
  }
  feedback(id, source, timestamp) {
    const turn = this.turns.get(id);
    if (!turn || turn.feedback || !Number.isFinite(timestamp)) return;
    turn.feedback = source;
    this.log("first_feedback", {id, source, commitToFeedbackMs:Math.round(1000*(timestamp-turn.deviceCommit))});
  }
  output(event) {
    const turn = this.turns.get(event.receipt);
    if (!turn || turn.ms !== undefined || !Number.isFinite(event.first_output)) return;
    this.feedback(event.receipt, "reply", event.first_output);
    turn.ms = Math.round(1000*(event.first_output-turn.vadEnd));
    const ttsMs = Math.round(1000*(event.first_output-event.tts_start));
    this.log("first_output", {id:event.receipt, vadEndToOutputMs:turn.ms, ttsToOutputMs:ttsMs,
      commitToOutputMs:Math.round(1000*(event.first_output-turn.deviceCommit))});
    return `First speaker callback ${turn.ms} ms · TTS ${ttsMs} ms`;
  }
  rate(score, note) {
    if (!this.last) return "Give a voice command first.";
    this.turns.get(this.last).score = score;
    this.log("rating", {id:this.last, score, note});
    return `Rated the latest command ${score}/5.`;
  }
  summary() {
    const turns = [...this.turns.values()];
    const ms = turns.map(t => t.ms).filter(Number.isFinite);
    const scores = turns.map(t => t.score).filter(Number.isFinite);
    const mean = values => values.reduce((sum,v) => sum + v, 0)/values.length;
    return `${turns.length} commands · ${ms.length} with audio · ${turns.length-ms.length} without measured audio` +
      (ms.length ? ` · mean ${Math.round(mean(ms))} ms` : "") +
      ` · ${scores.length} rated` + (scores.length ? ` · quality ${mean(scores).toFixed(1)}/5` : "");
  }
}
