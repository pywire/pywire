"""Base class for analysis rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Iterable

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity


class Rule(ABC):
    """Base class for all analysis rules.

    Subclasses declare a stable ``code`` (e.g. ``"PW001"``), a default
    severity, and implement ``check`` to return diagnostics for a single
    parsed file.
    """

    code: ClassVar[str]
    default_severity: ClassVar[Severity] = Severity.WARNING
    description: ClassVar[str] = ""

    @abstractmethod
    def check(self, ctx: AnalysisContext) -> Iterable[Diagnostic]: ...

    def diagnostic(
        self,
        ctx: AnalysisContext,
        *,
        line: int,
        column: int = 0,
        message: str,
        hint: str | None = None,
        severity: Severity | None = None,
    ) -> Diagnostic:
        from pywire_parser.analysis.diagnostics import Span

        return Diagnostic(
            code=self.code,
            severity=severity or self.default_severity,
            message=message,
            file_path=ctx.file_path,
            span=Span(line=line, column=column),
            hint=hint,
        )
