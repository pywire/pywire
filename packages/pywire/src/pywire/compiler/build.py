"""Build system for production."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from pywire.compiler.build_artifacts import BuildSummary


def fingerprint_static_assets(static_dir: Path, out_dir: Path) -> Dict[str, str]:
    """Copy static assets with content-hash filenames for cache busting.

    Returns a manifest mapping original relative paths to fingerprinted filenames.
    """
    manifest: Dict[str, str] = {}
    build_static_dir = out_dir / "static"

    if build_static_dir.exists():
        shutil.rmtree(build_static_dir)
    build_static_dir.mkdir(parents=True, exist_ok=True)

    for file_path in static_dir.rglob("*"):
        if not file_path.is_file():
            continue

        rel_path = file_path.relative_to(static_dir)
        content_hash = hashlib.md5(file_path.read_bytes()).hexdigest()[:12]

        # logo.png -> logo.a1b2c3d4e5f6.png
        stem = file_path.stem
        suffix = file_path.suffix
        fingerprinted_name = f"{stem}.{content_hash}{suffix}"
        fingerprinted_rel = rel_path.parent / fingerprinted_name

        dest = build_static_dir / fingerprinted_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)

        # Also copy the original filename so non-fingerprinted URLs still resolve
        original_dest = build_static_dir / rel_path
        original_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, original_dest)

        manifest[str(rel_path)] = str(fingerprinted_rel)

    # Write manifest
    manifest_path = out_dir / "asset-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return manifest


def build_project(
    optimize: bool = False,
    pages_dir: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    static_dir: Optional[Path] = None,
) -> BuildSummary:
    """Build project for production."""
    if pages_dir is None:
        pages_dir = Path("pages")

    from pywire.compiler.build_artifacts import build_artifacts
    from pywire.compiler.validate import validate_project

    errors = validate_project(pages_dir=pages_dir)
    if errors:
        raise ValueError(f"Build failed with {len(errors)} errors")

    summary = build_artifacts(pages_dir=pages_dir, out_dir=out_dir, optimize=optimize)

    # Fingerprint static assets if a static directory exists
    if static_dir is None:
        # Auto-discover: check for static/ relative to pages_dir parent
        candidate = pages_dir.parent / "static"
        if candidate.is_dir():
            static_dir = candidate

    if static_dir is not None and static_dir.is_dir():
        resolved_out = out_dir if out_dir is not None else summary.out_dir
        manifest = fingerprint_static_assets(static_dir, resolved_out)
        summary.static_assets = len(manifest)

    return summary
