"""Operator-selected roles. No credentials, endpoints or models are inferred."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit


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

    def __post_init__(self) -> None:
        if self.profile not in {"qwen", "nemotron"}:
            raise ValueError("ME3_FOREGROUND_PROFILE must be qwen or nemotron")
        http_url(self.base_url)
        if not self.model or self.model != self.model.strip():
            raise ValueError("Set ME3_FOREGROUND_MODEL to the exact served ID")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ForegroundConfig:
        required = ("PROFILE", "BASE_URL", "MODEL")
        if any(not env.get("ME3_FOREGROUND_" + name) for name in required):
            raise ValueError("Set ME3_FOREGROUND_PROFILE, BASE_URL and MODEL")
        return cls(
            *(env["ME3_FOREGROUND_" + name] for name in required),
            env.get("ME3_FOREGROUND_API_KEY", ""),
        )
