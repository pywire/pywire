"""Configuration, read once from the environment.

``pywire dev`` and ``pywire run`` load ``.env`` from the project root before
the app is imported, so a local ``.env`` (see ``.env.example``) is enough.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    typesafe_api_key: str
    # OpenRouter models tried in order for every writing step: drafting the
    # form, options for a choice field, sample answers.
    writer_models: Tuple[str, ...]
    jev_model: str
    stateless: bool
    # Header holding the visitor's real IP, set by a proxy you trust
    # (cf-connecting-ip on Cloudflare). Empty: use the socket address.
    client_ip_header: str
    # Builds, refines and sample fills allowed per window.
    visitor_limit: int
    ip_limit: int
    limit_window: int

    @property
    def configured(self) -> bool:
        return bool(self.openrouter_api_key and self.typesafe_api_key)


# Free first: a stealth model while it lasts, then the best free open models,
# then a cheap paid one so the demo keeps working when the free ones don't.
WRITER_MODELS = (
    "stealth/space-bunny-alpha",
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "deepseek/deepseek-v4-flash",
)


def _models(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    value = os.environ.get(name, "")
    models = tuple(m.strip() for m in value.split(",") if m.strip())
    return models or default


def load() -> Settings:
    return Settings(
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        typesafe_api_key=os.environ.get("TYPESAFE_API_KEY", ""),
        writer_models=_models("WRITER_MODELS", WRITER_MODELS),
        jev_model=os.environ.get("JEV_MODEL", "jev-latest"),
        stateless=os.environ.get("STATELESS", "1") != "0",
        client_ip_header=os.environ.get("CLIENT_IP_HEADER", "").lower(),
        visitor_limit=_int("VISITOR_LIMIT", 10),
        ip_limit=_int("IP_LIMIT", 30),
        limit_window=_int("LIMIT_WINDOW", 600),
    )


settings = load()
