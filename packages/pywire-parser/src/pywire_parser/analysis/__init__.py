"""Static analysis for .wire files.

The rule engine lives here so ``pywire check``, ``pywire build``, and the
PyWire language server can all consume the same diagnostics. See
``ROADMAP.md`` for the evolution plan (type-flow, ty integration,
cross-file rules).
"""

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity, Span
from pywire_parser.analysis.engine import analyze, analyze_files
from pywire_parser.analysis.registry import (
    all_rule_codes,
    get_rule,
    register_rule,
    rules_by_code,
)

__all__ = [
    "AnalysisContext",
    "Diagnostic",
    "Severity",
    "Span",
    "analyze",
    "analyze_files",
    "all_rule_codes",
    "get_rule",
    "register_rule",
    "rules_by_code",
]
