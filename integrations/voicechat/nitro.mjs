// Pi supplies the model family's request format. OpenRouter receives the pinned snapshot.
export function nitroTarget(family = "deepseek/deepseek-v4.1-flash") {
  if (family === "openai/gpt-oss-120b")
    return {model:"openai/gpt-oss-120b:nitro", requestedProvider:"Cerebras"};
  if (family === "deepseek/deepseek-v4.1-flash")
    return {model:"deepseek/deepseek-v4.1-flash-20261017:nitro", requestedProvider:"nebius/fp4"};
  throw Error("Unknown Nitro model profile: " + family);
}

export function routeNitro(pi, limit = 4096, honorThinkingOff = false) {
  pi.on("before_provider_request", ({payload}) => {
    const {model, requestedProvider} = nitroTarget(payload.model);
    const field = "max_completion_tokens" in payload ? "max_completion_tokens" : "max_tokens";
    return {
      ...payload,
      [field]:Math.min(payload[field] ?? limit,limit),
      model,
      ...(honorThinkingOff && requestedProvider === "nebius/fp4" && pi.getThinkingLevel?.() === "off"
        ? {reasoning:{effort:"none"}} : {}),
      provider:{...payload.provider, only:[requestedProvider], sort:"throughput", allow_fallbacks:false, require_parameters:true},
    };
  });
}

export default function nitro(pi) {
  routeNitro(pi,2048,true);
}
