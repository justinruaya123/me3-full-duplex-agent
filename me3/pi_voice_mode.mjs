// One microphone attachment per Pi session. The host continues supervising jobs
// while the operator pauses voice or Pi replaces the chat.
export function voiceMode(ask, status) {
  let state = "off";
  let profile = "verified";
  let session, watchdog;

  function watchCapture() {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => setState("stalled"), 3000);
    watchdog.unref?.();
  }

  function setState(next) {
    state = next;
    const label = profile === "demo" ? "trusted-room demo" : "owner-verified mode";
    const labels = {
      off: "Voice paused · /me3 duplex or F6 to resume",
      starting: "Opening microphone · " + label,
      waiting: "Audio output open · waiting for microphone frames · " + label + " · /me3 duplex to pause",
      listening: "Full duplex · listening · " + label + " · /me3 duplex or F6 to pause",
      stalled: "No microphone frames for 3 seconds · check the input device or toggle /me3 duplex",
      stopping: "Closing microphone",
      unknown: "Microphone status unknown · /me3 duplex or F6 to retry pause",
    };
    status(labels[next]);
  }

  async function enter(selected = profile) {
    if (state !== "off") return;
    profile = selected;
    session = undefined;
    setState("starting");
    try {
      return await ask("voice", profile === "demo" ? "demo" : "");
    } catch (error) {
      if (state === "starting") {
        setState(error.message === "ME3 host response timed out" ? "unknown" : "off");
      }
      throw error;
    }
  }

  async function leave(operation = "end") {
    if (state === "stopping") return;
    clearTimeout(watchdog);
    setState("stopping");
    try {
      const result = await ask(operation);
      setState("off");
      return result;
    } catch (error) {
      if (state !== "off") setState("unknown");
      throw error;
    }
  }

  return {
    enter, leave,
    toggle: () => state === "off" ? enter() : leave(),
    get resumeProfile() {
      return ["starting", "waiting", "listening", "stalled"].includes(state) ? profile : "off";
    },
    observe(kind, id) {
      if (kind === "voice_open" && state === "starting") {
        session = id;
        setState("waiting");
        watchCapture();
      } else if (kind === "mic_level" && id === session &&
                 ["waiting", "listening", "stalled"].includes(state)) {
        if (state !== "listening") setState("listening");
        watchCapture();
      } else if (kind === "host_stopped" ||
                 (kind === "voice_closed" && (!session || !id || id === session))) {
        clearTimeout(watchdog);
        session = undefined;
        if (state !== "stopping" || kind === "host_stopped") setState("off");
      }
    },
    async start(uiMode, reason, selected) {
      if (uiMode !== "tui" && (uiMode !== "rpc" || !selected)) return;
      if (selected !== undefined && !["verified", "demo", "off"].includes(selected)) {
        throw Error("Choose verified, demo or off for the ME3 voice mode");
      }
      if (state !== "off") return;
      if (selected && selected !== "off") profile = selected;
      if (reason === "startup" && selected !== "off") return enter();
      setState("off");
    },
  };
}
