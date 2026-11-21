// These rows only go to Pi's widget API. Microphone revisions never become agent inputs.
const speech = {
  speech_script: "ME3 · synthesizing",
  speech_audio: "ME3 · audio started",
  speech_interrupted: "ME3 · interrupted",
  speech_complete: "ME3 · playback complete",
  speech_failed: "ME3 · speech failed",
};

export function voiceWidget(draw, drawMic = () => {}) {
  let session, peak, partialTurn, lastFooter;
  let partial = "";
  const rows = new Map();

  function paintMic() {
    let line = "Mic · waiting for input";
    if (peak !== undefined) {
      const db = Math.round(20 * Math.log10(peak / 32768));
      const bars = Math.max(0, Math.min(10, Math.round((db + 60) / 6)));
      const value = peak === 0 ? "−∞" : String(db).replace("-", "−");
      line = "Mic " + "█".repeat(bars) + "░".repeat(10 - bars) + " " + value + " dBFS";
    }
    if (partial) line += " · Hearing  " + (partial.length > 80 ? "…" + partial.slice(-79) : partial);
    if (line !== lastFooter) drawMic(line);
    lastFooter = line;
  }

  return event => {
    const {kind, session_id, revision} = event;
    if (kind === "voice_open") {
      session = session_id;
      peak = partialTurn = lastFooter = undefined;
      partial = "";
      rows.clear();
      draw([]);
      paintMic();
      return;
    }
    if (!session || session_id !== session) return;
    if (kind === "voice_closed") {
      session = undefined;
      rows.clear();
      draw(undefined);
      drawMic(undefined);
      return;
    }
    if (kind === "mic_level") {
      if (Number.isInteger(event.peak) && event.peak >= 0 && event.peak <= 32768) {
        peak = event.peak;
        paintMic();
      }
      return;
    }

    const text = String(event.text ?? "").replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]+/gu, " ").trim().slice(0, 1600);
    if (["asr_partial", "asr_final", "asr_backchannel"].includes(kind)) {
      const key = "turn:" + event.turn_id;
      const previous = rows.get(key);
      if (previous && (previous.final || previous.revision > revision)) return;
      const final = kind !== "asr_partial";
      const label = kind === "asr_backchannel" ? "You · backchannel" : "You";
      rows.set(key, {text, label, revision, final, partial: !final});
      if (!final || partialTurn === key) {
        partial = final ? "" : text;
        partialTurn = final ? undefined : key;
        paintMic();
      }
    } else if (kind === "companion") {
      rows.set(Symbol(), {text, label: "ME3 · details"});
    } else if (Object.hasOwn(speech, kind)) {
      const key = "speech:" + event.utterance;
      const row = rows.get(key);
      if (kind === "speech_script") rows.set(key, {text, label: speech[kind]});
      else if (row && !row.final) {
        row.label = speech[kind];
        row.final = kind !== "speech_audio";
      } else return;
    } else return;

    if (rows.size > 6) rows.delete(rows.keys().next().value);
    if (kind !== "asr_partial") {
      draw(Array.from(rows.values()).filter(row => !row.partial).map(row => row.label + "  " + row.text));
    }
  };
}
