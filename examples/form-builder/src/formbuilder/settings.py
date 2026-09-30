"""Configuration, read once from the environment.

``pywire dev`` and ``pywire run`` load ``.env`` from the project root before
the app is imported, so a local ``.env`` (see ``.env.example``) is enough.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    typesafe_api_key: str
    # Drafts the form and rewrites it on refine.
    writer_model: str
    # Small jobs: options for a choice field, sample answers.
    helper_model: str
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
        return bool(self.groq_api_key and self.typesafe_api_key)


def load() -> Settings:
    return Settings(
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        typesafe_api_key=os.environ.get("TYPESAFE_API_KEY", ""),
        writer_model=os.environ.get("WRITER_MODEL", "openai/gpt-oss-120b"),
        helper_model=os.environ.get("HELPER_MODEL", "openai/gpt-oss-20b"),
        jev_model=os.environ.get("JEV_MODEL", "jev-latest"),
        stateless=os.environ.get("STATELESS", "1") != "0",
        client_ip_header=os.environ.get("CLIENT_IP_HEADER", "").lower(),
        visitor_limit=_int("VISITOR_LIMIT", 10),
        ip_limit=_int("IP_LIMIT", 30),
        limit_window=_int("LIMIT_WINDOW", 600),
    )


settings = load()
