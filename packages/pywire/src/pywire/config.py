"""Lightweight env-var config.

PyWire follows 12-factor: configuration lives in environment variables.
This module adds a small ergonomic wrapper + cascading ``.env`` file
auto-loading on first use. There is deliberately no ``Settings`` class —
if you need typed structured config, use ``pydantic-settings`` directly.

Cascade order (later wins for unset keys, real env vars always win):

1. Real process environment
2. ``.env.<PYWIRE_MODE>`` (if ``PYWIRE_MODE`` is set)
3. ``.env.local``
4. ``.env``

The cascade is loaded once on first call to ``env()`` and cached.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Union, overload

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_MISSING: Any = object()

_LOADED = False
_LOAD_LOCK = threading.Lock()


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal ``.env`` parser. No nested expansion, no inline comments
    after values, but supports quoted values and export prefixes."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def _load_dotenv(search_from: Optional[Path] = None) -> None:
    """Populate ``os.environ`` from cascading ``.env`` files (real env wins)."""
    start = (search_from or Path.cwd()).resolve()

    candidates = [start, *start.parents]
    found_dir: Optional[Path] = None
    for candidate in candidates:
        if (candidate / ".env").is_file() or (candidate / ".env.local").is_file():
            found_dir = candidate
            break
    if found_dir is None:
        found_dir = start

    mode = os.environ.get("PYWIRE_MODE")
    files: list[Path] = []
    if mode:
        files.append(found_dir / f".env.{mode}")
    files.append(found_dir / ".env.local")
    files.append(found_dir / ".env")

    for path in files:
        if not path.is_file():
            continue
        for key, value in _parse_env_file(path).items():
            os.environ.setdefault(key, value)


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOAD_LOCK:
        if _LOADED:
            return
        _load_dotenv()
        _LOADED = True


def reload(search_from: Optional[Path] = None) -> None:
    """Re-run the ``.env`` cascade (test / long-running dev use)."""
    global _LOADED
    with _LOAD_LOCK:
        _load_dotenv(search_from)
        _LOADED = True


def _cast_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def _cast_int(raw: str) -> int:
    return int(raw)


def _cast_float(raw: str) -> float:
    return float(raw)


@overload
def env(key: str) -> Optional[str]: ...


@overload
def env(key: str, *, required: bool) -> str: ...


@overload
def env(key: str, *, default: _T) -> Union[str, _T]: ...


@overload
def env(
    key: str, *, cast: Callable[[str], _T], default: _T
) -> _T: ...


@overload
def env(
    key: str, *, cast: Callable[[str], _T], required: bool
) -> _T: ...


def env(
    key: str,
    *,
    default: Any = _MISSING,
    cast: Optional[Any] = None,
    required: bool = False,
) -> Any:
    """Read an env var.

    ``cast`` may be ``bool``, ``int``, ``float``, or any callable
    ``str -> T``. ``bool`` uses truthy parsing ("1", "true", "yes", "on").
    """
    _ensure_loaded()

    raw = os.environ.get(key)
    if raw is None:
        if required:
            raise RuntimeError(f"Missing required env var: {key!r}")
        if default is _MISSING:
            return None
        return default

    if cast is None:
        return raw
    if cast is bool:
        return _cast_bool(raw)
    if cast is int:
        return _cast_int(raw)
    if cast is float:
        return _cast_float(raw)
    return cast(raw)
