"""Helpers for PyWire filesystem paths."""

from __future__ import annotations

from pathlib import Path


def ensure_pywire_folder() -> Path:
    """Ensure .pywire exists and has a local .gitignore."""
    dot_pywire = Path(".pywire")
    if not dot_pywire.exists():
        dot_pywire.mkdir()

    gitignore_path = dot_pywire / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("*")

    return dot_pywire


def get_pywire_path(*parts: str) -> Path:
    """Return a path inside .pywire/."""
    dot_pywire = ensure_pywire_folder()
    return dot_pywire.joinpath(*parts)


def get_build_path(*parts: str) -> Path:
    """Return a path inside .pywire/build/."""
    return get_pywire_path("build", *parts)
