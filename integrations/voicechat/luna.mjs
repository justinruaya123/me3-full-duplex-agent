// Pi's Codex adapter omits reasoning from the wire request at thinking level off.
export default function lunaVoice(pi) {
  pi.on("before_provider_request", ({ payload }) => ({
    ...payload,
    reasoning: { effort: "none" },
  }));
}
