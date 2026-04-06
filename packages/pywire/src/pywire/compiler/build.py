"""Build system for production."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pywire.compiler.build_artifacts import BuildSummary


def build_project(
    optimize: bool = False,
    pages_dir: Optional[Path] = None,
    out_dir: Optional[Path] = None,
) -> BuildSummary:
    """Build project for production."""
    if pages_dir is None:
        pages_dir = Path("pages")

    from pywire.cli.validate import validate_project
    from pywire.compiler.build_artifacts import build_artifacts

    errors = validate_project(pages_dir=pages_dir)
    if errors:
        raise ValueError(f"Build failed with {len(errors)} errors")

    return build_artifacts(pages_dir=pages_dir, out_dir=out_dir, optimize=optimize)
