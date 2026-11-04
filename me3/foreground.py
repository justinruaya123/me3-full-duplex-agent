"""Streaming OpenAI-compatible foreground inference, with no tool authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from me3.configuration import ForegroundConfig


class ForegroundBackend:
    def __init__(self, config: ForegroundConfig, *, client=None) -> None:
        self.config, self.client = config, client

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        import httpx

        if not prompt.strip() or len(prompt) > 100_000:
            raise ValueError("Invalid foreground prompt")
        if self.client is None:
            async with httpx.AsyncClient(timeout=60) as client:
                async for text in self._stream(client, prompt):
                    yield text
        else:
            async for text in self._stream(self.client, prompt):
                yield text

    async def _stream(self, client, prompt: str) -> AsyncIterator[str]:
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        payload = {
            "model": self.config.model,
            "stream": True,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False},
        }
        total = 0
        async with client.stream(
            "POST",
            self.config.base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if len(line) > 65536:
                    raise ValueError("Foreground event exceeds limit")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                record = json.loads(data)
                if record.get("model") != self.config.model:
                    raise ValueError("Foreground model ID changed or missing")
                for choice in record.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("tool_calls") or delta.get("function_call"):
                        raise ValueError("Foreground tools are disabled")
                    if delta.get("reasoning_content") or delta.get(
                        "reasoning"
                    ):
                        raise ValueError(
                            "Foreground reasoning is not disabled"
                        )
                    text = delta.get("content")
                    if text:
                        if not isinstance(text, str):
                            raise ValueError("Invalid foreground text")
                        total += len(text)
                        if total > 16000:
                            raise ValueError("Foreground output exceeds limit")
                        yield text

    async def run(
        self,
        prompt: str,
        workspace: Path,
        *,
        foreground: bool = False,
    ) -> str:
        return "".join([text async for text in self.stream(prompt)])
