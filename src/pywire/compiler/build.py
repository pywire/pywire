"""Build system for production."""

from pathlib import Path
from typing import Optional


def build_project(optimize: bool = False, pages_dir: Optional[Path] = None) -> None:
    """Build project for production."""
    if pages_dir is None:
        pages_dir = Path("pages")

    # For now, just validate compilation
    # Future: cache compiled pages, optimize, etc.
    from pywire.cli.validate import validate_project

    errors = validate_project(pages_dir=pages_dir)
    if errors:
        raise ValueError(f"Build failed with {len(errors)} errors")
