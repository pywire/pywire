"""Validation for .pywire files."""

from pathlib import Path
from typing import List

from pywire.compiler.parser import PyWireParser


def validate_project(pages_dir: Path) -> List[str]:
    """Validate all .pywire files in project."""
    errors = []
    parser = PyWireParser()

    if not pages_dir.exists():
        return [f"Pages directory not found: {pages_dir}"]

    for pywire_file in pages_dir.rglob("*.pywire"):
        try:
            parsed = parser.parse_file(pywire_file)
            # Basic validation
            if not parsed.template and not parsed.directives:
                errors.append(f"{pywire_file}: No template or directives found")
        except Exception as e:
            errors.append(f"{pywire_file}: {str(e)}")

    return errors
