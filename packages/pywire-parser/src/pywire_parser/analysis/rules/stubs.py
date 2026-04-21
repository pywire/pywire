"""Stubs for rules that are scoped for a future iteration.

Each class registers a code so ``pywire check --rule`` can see it, but
``check`` raises ``NotImplementedError`` — the engine skips stubs
silently. Fill these in as rules are promoted off the ROADMAP.
"""

from __future__ import annotations

from typing import Iterable

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity
from pywire_parser.analysis.registry import register_rule
from pywire_parser.analysis.rules.base import Rule


class _Stub(Rule):
    default_severity = Severity.WARNING

    def check(self, ctx: AnalysisContext) -> Iterable[Diagnostic]:  # pragma: no cover
        raise NotImplementedError(f"{self.code} not implemented yet")


@register_rule
class WirePrimitiveSubscript(_Stub):
    code = "PW004"
    description = "subscripting a WirePrimitive (use .value[...] instead)"


@register_rule
class WireListConcatLosesReactivity(_Stub):
    code = "PW005"
    description = "wire_list + other — result is a plain list, not reactive"


@register_rule
class StoreInterpolatedWithoutValue(_Stub):
    code = "PW006"
    description = "store interpolated into template without .value"


@register_rule
class DerivedAugmentedAssign(_Stub):
    code = "PW007"
    description = "derived += x — Derived has no __iadd__"


@register_rule
class DerivedCalledAsFunction(_Stub):
    code = "PW008"
    description = "calling a Derived — raises TypeError"


@register_rule
class EffectNotAssigned(_Stub):
    code = "PW009"
    description = "effect() result discarded — cannot dispose"


@register_rule
class RefAccessedBeforeBind(_Stub):
    code = "PW010"
    description = "ref.value / ref.data accessed on unbound HTMLElement"
