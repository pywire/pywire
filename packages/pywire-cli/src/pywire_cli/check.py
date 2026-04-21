"""`pywire check` — static analysis for a PyWire project.

Thin CLI layer over :mod:`pywire_parser.analysis`. Supports rich output by
default and a ruff-style ``--plain`` format for CI / greppable logs. Exits
1 on any ERROR-severity diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from pywire_parser.analysis import Diagnostic, Severity, analyze_files
from pywire_parser.analysis.registry import all_rule_codes
from pywire_parser.parser import PyWireParser


@dataclass(frozen=True)
class CheckSummary:
    errors: int
    warnings: int
    infos: int
    exit_code: int

    @property
    def total(self) -> int:
        return self.errors + self.warnings + self.infos


def collect_diagnostics(
    pages_dir: Path,
    *,
    rule_codes: Optional[Sequence[str]] = None,
) -> List[Diagnostic]:
    """Parse every ``.wire`` under ``pages_dir`` and run the analysis engine."""
    parser = PyWireParser()
    items = []
    if not pages_dir.exists():
        return []
    for wire_file in sorted(pages_dir.rglob("*.wire")):
        try:
            parsed = parser.parse_file(wire_file)
        except Exception as e:  # noqa: BLE001 — surface parse errors as diags
            items.append(_parse_error_diag(wire_file, e))
            continue
        items.append((parsed, wire_file))
    # Split: tuples go to engine; parse-error diagnostics are already Diagnostic
    parsed_items = [x for x in items if isinstance(x, tuple)]
    parse_error_diags = [x for x in items if not isinstance(x, tuple)]
    engine_diags = analyze_files(parsed_items, codes=rule_codes)
    return parse_error_diags + engine_diags


def _parse_error_diag(path: Path, err: Exception) -> Diagnostic:
    from pywire_parser.analysis.diagnostics import Span

    return Diagnostic(
        code="PW000",
        severity=Severity.ERROR,
        message=f"parse error: {err}",
        file_path=str(path),
        span=Span(line=1, column=0),
    )


def format_plain(diags: Iterable[Diagnostic]) -> str:
    lines = []
    for d in diags:
        lines.append(
            f"{d.file_path}:{d.line}:{d.column}: {d.severity.value} [{d.code}] {d.message}"
        )
    return "\n".join(lines)


def format_rich(diags: Iterable[Diagnostic], console) -> None:
    """Render diagnostics with rich markup. ``console`` is a rich Console."""
    current_file: Optional[str] = None
    sev_style = {
        Severity.ERROR: "bold red",
        Severity.WARNING: "yellow",
        Severity.INFO: "cyan",
    }
    for d in diags:
        if d.file_path != current_file:
            console.print(f"\n[bold]{d.file_path}[/]")
            current_file = d.file_path
        style = sev_style[d.severity]
        console.print(
            f"  [dim]{d.line}:{d.column}[/]  "
            f"[{style}]{d.severity.value}[/]  "
            f"[bold]{d.code}[/]  {d.message}"
        )
        if d.hint:
            console.print(f"    [dim]→ {d.hint}[/]")


def summarize(diags: Iterable[Diagnostic], *, strict: bool = False) -> CheckSummary:
    errors = sum(1 for d in diags if d.severity == Severity.ERROR)
    warnings = sum(1 for d in diags if d.severity == Severity.WARNING)
    infos = sum(1 for d in diags if d.severity == Severity.INFO)
    exit_code = 0
    if errors > 0:
        exit_code = 1
    elif strict and (warnings > 0 or infos > 0):
        exit_code = 1
    return CheckSummary(errors, warnings, infos, exit_code)


__all__ = [
    "CheckSummary",
    "collect_diagnostics",
    "format_plain",
    "format_rich",
    "summarize",
    "all_rule_codes",
]
