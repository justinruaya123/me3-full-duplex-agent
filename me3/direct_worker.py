"""Inference-only HTTP adapter for jobs owned by the local supervisor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from me3.configuration import OPENROUTER_BASE_URL, http_url, pinned_route, worker_pin


@dataclass
class DirectWorker:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    routing_provider: str = ""
    serving_name: str = ""
    client: object = field(default=None, repr=False)
    verified_provider: str | None = field(default=None, init=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> DirectWorker:
        provider = env.get("ME3_WORKER_PROVIDER", "")
        model = env.get("ME3_WORKER_MODEL", "")
        url = env.get("ME3_WORKER_BASE_URL", "")
        if not model or model.strip() != model:
            raise ValueError("Set ME3_WORKER_MODEL to the exact served ID")
        if provider == "openrouter":
            if url and url.rstrip("/") != OPENROUTER_BASE_URL:
                raise ValueError("OpenRouter worker requires the OpenRouter endpoint")
            key = env.get("OPENROUTER_API_KEY", "")
            if not key.strip():
                raise ValueError("Set OPENROUTER_API_KEY")
            return cls(provider, model, OPENROUTER_BASE_URL, key, *worker_pin(env, model))
        if provider not in {"qwen", "compatible"}:
            raise ValueError("Direct ME3_WORKER_PROVIDER must be qwen, compatible or openrouter")
        if not url:
            raise ValueError("Set ME3_WORKER_BASE_URL")
        return cls(provider, model, http_url(url), env.get("ME3_WORKER_API_KEY", ""))

    async def run(self, prompt: str, workspace: Path, *, foreground: bool = False) -> str:
        import httpx

        if foreground:
            raise ValueError("The direct worker accepts only delegated jobs")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100_000:
            raise ValueError("Invalid worker prompt")
        self.verified_provider = None
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 8192,
        }
        if self.provider == "openrouter":
            body.update(provider=pinned_route(self.routing_provider), reasoning={"effort": "medium"})
        elif self.provider == "qwen":
            body["chat_template_kwargs"] = {"enable_thinking": False}
        if self.client is None:
            async with httpx.AsyncClient(timeout=600) as client:
                return await self._complete(client, body)
        return await self._complete(self.client, body)

    async def _complete(self, client, body: dict) -> str:
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        async with client.stream("POST", self.base_url + "/chat/completions",
                                 headers=headers, json=body) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > 1_048_576:
                    raise ValueError("Worker completion exceeds limit")
                data.extend(chunk)
        record = json.loads(data)
        if record.get("error"):
            raise RuntimeError("Worker provider reported an error")
        if record.get("model") != self.model:
            raise ValueError("Worker model ID changed or missing")
        if self.provider == "openrouter" and record.get("provider") != self.serving_name:
            raise ValueError("Worker route changed or missing")
        choices = record.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Expected exactly one worker completion")
        choice = choices[0]
        message = choice.get("message", {})
        if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
                or message.get("function_call") or message.get("refusal")):
            raise ValueError("Worker returned an incomplete or unsupported result")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Worker returned no usable text")
        if self.provider == "openrouter":
            self.verified_provider = record["provider"]
        return text
