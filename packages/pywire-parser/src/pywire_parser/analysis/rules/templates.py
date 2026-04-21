"""PW003 — redundant ``.value`` in template interpolation.

``{count}`` auto-unwraps via ``unwrap_wire``; ``{count.value}`` produces
identical output and only adds noise. Flag the attribute form whenever the
base name is a known wire / derived.
"""

from __future__ import annotations

import ast
from typing import Iterable

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity
from pywire_parser.analysis.registry import register_rule
from pywire_parser.analysis.rules.base import Rule
from pywire_parser.ast_nodes import InterpolationNode, TemplateNode


def _iter_interpolations(nodes: Iterable[TemplateNode]):
    for node in nodes:
        for attr in node.special_attributes:
            if isinstance(attr, InterpolationNode):
                yield attr
        for child in node.children:
            yield from _iter_interpolations([child])


@register_rule
class RedundantValueInInterpolation(Rule):
    code = "PW003"
    default_severity = Severity.INFO
    description = "redundant .value in template interpolation"

    def check(self, ctx: AnalysisContext) -> Iterable[Diagnostic]:
        watchable = ctx.wire_names | ctx.derived_names
        if not watchable:
            return
        for interp in _iter_interpolations(ctx.parsed.template):
            try:
                expr = ast.parse(interp.expression, mode="eval").body
            except SyntaxError:
                continue
            if (
                isinstance(expr, ast.Attribute)
                and isinstance(expr.value, ast.Name)
                and expr.value.id in watchable
                and expr.attr == "value"
            ):
                name = expr.value.id
                yield self.diagnostic(
                    ctx,
                    line=interp.line,
                    column=interp.column,
                    message=(
                        f"redundant .value in template interpolation: "
                        f"{{{name}.value}} behaves identically to {{{name}}}"
                    ),
                    hint=f"Replace with {{{name}}}.",
                )
