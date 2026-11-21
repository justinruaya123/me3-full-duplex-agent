"""Operator-selected roles. No credentials, endpoints or models are inferred."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping
from urllib.parse import urlsplit

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
FLASH_LITE = "google/gemini-2.5-flash-lite"
GPT_OSS = "openai/gpt-oss-120b"


def pinned_route(provider: str) -> dict:
    return {
        "only": [provider], "allow_fallbacks": False, "require_parameters": True,
    }


def validate_serving_pin(slug: str, name: str) -> None:
    if (not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", slug)
            or not name or name != name.strip() or len(name) > 128
            or not name.isprintable()):
        raise ValueError("Set the OpenRouter provider slug and exact serving name")


def worker_pin(env: Mapping[str, str], model: str) -> tuple[str, str]:
    slug = env.get("ME3_WORKER_ROUTING_PROVIDER", "")
    name = env.get("ME3_WORKER_ROUTING_PROVIDER_NAME", "")
    if model == GPT_OSS and slug in {"", "cerebras"} and not name:
        return "cerebras", "Cerebras"
    validate_serving_pin(slug, name)
    return slug, name


def http_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Use an HTTP(S) base URL without embedded credentials"
        )
    return value.rstrip("/")


@dataclass(frozen=True)
class ForegroundConfig:
    profile: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    provider: str = ""
    provider_name: str = ""
    stop: str = ""
    task_actions: bool = False

    def __post_init__(self) -> None:
        if self.profile not in {"qwen", "nemotron", "compatible", "pi-fast", "pi-chat", "openrouter"}:
            raise ValueError(
                "ME3_FOREGROUND_PROFILE must be qwen, nemotron, compatible, pi-fast, pi-chat or openrouter"
            )
        if self.profile == "openrouter":
            if self.base_url.rstrip("/") != OPENROUTER_BASE_URL:
                raise ValueError("OpenRouter requires the OpenRouter endpoint")
            if self.provider_name or (self.model, self.provider) != (FLASH_LITE, "google-ai-studio"):
                validate_serving_pin(self.provider, self.provider_name)
            if not self.api_key.strip():
                raise ValueError("Set OPENROUTER_API_KEY")
        if self.profile in {"pi-fast", "pi-chat"}:
            if not self.provider.strip():
                raise ValueError("Set ME3_FOREGROUND_PROVIDER for the Pi foreground profile")
        else:
            http_url(self.base_url)
        if not self.model or self.model != self.model.strip():
            raise ValueError("Set ME3_FOREGROUND_MODEL to the exact served ID")
        if self.stop and (len(self.stop) > 128 or self.profile != "compatible"):
            raise ValueError("ME3_FOREGROUND_STOP supports up to 128 characters in compatible mode")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ForegroundConfig:
        if env.get("ME3_FOREGROUND_PROFILE") in {"pi-fast", "pi-chat"}:
            return cls(
                env["ME3_FOREGROUND_PROFILE"], "", env.get("ME3_FOREGROUND_MODEL", ""), "",
                env.get("ME3_FOREGROUND_PROVIDER", ""),
            )
        required = ("PROFILE", "BASE_URL", "MODEL")
        if any(not env.get("ME3_FOREGROUND_" + name) for name in required):
            raise ValueError("Set ME3_FOREGROUND_PROFILE, BASE_URL and MODEL")
        return cls(
            *(env["ME3_FOREGROUND_" + name] for name in required),
            env.get("OPENROUTER_API_KEY", "")
            if env["ME3_FOREGROUND_PROFILE"] == "openrouter"
            else env.get("ME3_FOREGROUND_API_KEY", ""),
            env.get("ME3_FOREGROUND_PROVIDER", ""),
            env.get("ME3_FOREGROUND_PROVIDER_NAME", ""),
            env.get("ME3_FOREGROUND_STOP", ""),
            env.get("ME3_FOREGROUND_TASK_ACTIONS") == "1",
        )
