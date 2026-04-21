"""Validation for .wire files."""

from pathlib import Path
from typing import List

from pywire.compiler.parser import PyWireParser


def validate_project(pages_dir: Path) -> List[str]:
    """Validate all .wire files in project."""
    errors: List[str] = []
    parser = PyWireParser()

    if not pages_dir.exists():
        return [f"Pages directory not found: {pages_dir}"]

    for wire_file in pages_dir.rglob("*.wire"):
        try:
            parsed = parser.parse_file(wire_file)
            if not parsed.template and not parsed.directives:
                errors.append(f"{wire_file}: No template or directives found")
        except Exception as e:
            errors.append(f"{wire_file}: {str(e)}")

    return errors
