"""Analysis engine — runs rules over parsed .wire files."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from pywire_parser.analysis.context import build_context
from pywire_parser.analysis.diagnostics import Diagnostic
from pywire_parser.analysis.registry import rules_by_code
from pywire_parser.ast_nodes import ParsedPyWire

# Import rules so they register themselves.
from pywire_parser.analysis.rules import serialization  # noqa: F401
from pywire_parser.analysis.rules import reactivity  # noqa: F401
from pywire_parser.analysis.rules import templates  # noqa: F401
from pywire_parser.analysis.rules import stubs  # noqa: F401


def analyze(
    parsed: ParsedPyWire,
    file_path: str | Path,
    *,
    codes: Optional[Sequence[str]] = None,
) -> List[Diagnostic]:
    """Run enabled rules over a single parsed file."""
    ctx = build_context(parsed, str(file_path))
    rules = rules_by_code(list(codes) if codes else None)
    diagnostics: List[Diagnostic] = []
    for rule in rules:
        try:
            diagnostics.extend(rule.check(ctx))
        except NotImplementedError:
            continue
    diagnostics.sort(key=lambda d: (d.file_path, d.span.line, d.span.column, d.code))
    return diagnostics


def analyze_files(
    items: Iterable[tuple[ParsedPyWire, str | Path]],
    *,
    codes: Optional[Sequence[str]] = None,
) -> List[Diagnostic]:
    """Run rules over multiple parsed files."""
    out: List[Diagnostic] = []
    for parsed, path in items:
        out.extend(analyze(parsed, path, codes=codes))
    return out
