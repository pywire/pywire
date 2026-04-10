"""
PEP 517 build backend that builds TypeScript client assets before
delegating to maturin for the Rust extension + wheel packaging.

Source builds (from git or sdist) require Node.js and pnpm to compile
the client bundle, just as they require a Rust toolchain for the parser.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from maturin import (
    build_editable,
    build_sdist,
    build_wheel,
    get_requires_for_build_editable,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel,
)

log = logging.getLogger(__name__)

_ROOT = Path(__file__).parent
_CLIENT_DIR = _ROOT / "src" / "pywire" / "client"
_STATIC_DIR = _ROOT / "src" / "pywire" / "static"


def _build_client(*, required: bool = True) -> None:
    pkg_path = _CLIENT_DIR / "package.json"
    if not pkg_path.exists():
        return

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)

    pnpm = shutil.which("pnpm")
    if not pnpm:
        if (_STATIC_DIR / "pywire.core.min.js").exists():
            log.warning("pnpm not found, skipping client build (assets already exist).")
            return
        if not required:
            log.warning(
                "pnpm not found and client assets missing — skipping client build. "
                "Install Node.js and pnpm to build the client."
            )
            return
        raise RuntimeError(
            "pnpm not found and client assets missing. "
            "Install Node.js and pnpm to build from source."
        )

    nm = _CLIENT_DIR / "node_modules"
    if not nm.exists() or pkg_path.stat().st_mtime > nm.stat().st_mtime:
        log.info("Installing client dependencies...")
        subprocess.run(
            [pnpm, "install", "--frozen-lockfile"],
            cwd=_CLIENT_DIR,
            check=True,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "CI": "true"},
        )

    core_bundle = _STATIC_DIR / "pywire.core.min.js"
    needs_build = not core_bundle.exists()
    if not needs_build:
        bundle_mtime = core_bundle.stat().st_mtime
        for path in (_CLIENT_DIR / "src").rglob("*"):
            if path.is_file() and path.stat().st_mtime > bundle_mtime:
                needs_build = True
                break

    if needs_build:
        log.info("Building client assets...")
        subprocess.run(
            [pnpm, "run", "build"],
            cwd=_CLIENT_DIR,
            check=True,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "CI": "true"},
        )


# Re-export maturin hooks unchanged (metadata, requires)
__all__ = [
    "get_requires_for_build_wheel",
    "get_requires_for_build_sdist",
    "get_requires_for_build_editable",
    "prepare_metadata_for_build_wheel",
    "prepare_metadata_for_build_editable",
    "build_wheel",
    "build_sdist",
    "build_editable",
]

# Wrap the three build entry points to run the client build first

_orig_build_wheel = build_wheel
_orig_build_sdist = build_sdist
_orig_build_editable = build_editable


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _build_client()
    return _orig_build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _build_client()
    return _orig_build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    _build_client(required=False)
    return _orig_build_editable(wheel_directory, config_settings, metadata_directory)
