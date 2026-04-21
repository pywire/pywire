"""Diagnostic dataclasses shared across analysis rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Span:
    """Source location for a diagnostic. Columns are 0-indexed."""

    line: int
    column: int = 0
    end_line: Optional[int] = None
    end_column: Optional[int] = None


@dataclass(frozen=True)
class Diagnostic:
    """A single analysis finding.

    ``fix`` is reserved for a future ``pywire check --fix`` implementation;
    rules may return a non-None fix hint as free-form text for now.
    """

    code: str
    severity: Severity
    message: str
    file_path: str
    span: Span
    hint: Optional[str] = None
    fix: Optional[str] = None

    @property
    def line(self) -> int:
        return self.span.line

    @property
    def column(self) -> int:
        return self.span.column
