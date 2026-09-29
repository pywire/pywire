"""Configuration, read once from the environment.

``pywire dev`` and ``pywire run`` load ``.env`` from the project root before
the app is imported, so a local ``.env`` (see ``.env.example``) is enough.
"""

from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    if os.environ.get("PYWIRE_DEV_MODE") == "1" or os.environ.get("TASKBOARD_TESTING"):
        # Development only: a throwaway secret. Sessions and API tokens
        # stop working when the server restarts.
        warnings.warn(f"{name} is not set; using a temporary secret", stacklevel=2)
        return secrets.token_hex(32)
    raise RuntimeError(f"Set {name} (for example: openssl rand -hex 32)")


@dataclass(frozen=True)
class Settings:
    database_url: str
    upload_dir: Path
    idp_secret: str
    session_secret: str


def load() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", f"sqlite+aiosqlite:///{ROOT / 'var' / 'taskboard.db'}"
        ),
        upload_dir=Path(os.environ.get("UPLOAD_DIR", ROOT / "var" / "uploads")),
        idp_secret=_secret("LOCAL_IDP_SECRET"),
        session_secret=_secret("SESSION_SECRET"),
    )


settings = load()
