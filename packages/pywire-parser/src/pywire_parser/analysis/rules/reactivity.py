"""PW002 — writes to wires inside a ``derived`` body.

``derived`` is a pure computation; writing to a wire from within raises
``ReactivityError`` at runtime. Detectable statically when the ``derived``
body directly assigns to a known wire name or to ``wire_name.value``.
"""

from __future__ import annotations

import ast
from typing import Iterable, Set

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity
from pywire_parser.analysis.registry import register_rule
from pywire_parser.analysis.rules.base import Rule


def _derived_bodies(module: ast.Module) -> list[ast.AST]:
    """Collect all AST nodes that are the body of a derived computation."""
    bodies: list[ast.AST] = []
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                name = _deco_name(deco)
                if name == "derived":
                    bodies.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "derived":
                for a in node.args:
                    if isinstance(a, (ast.Lambda, ast.FunctionDef)):
                        bodies.append(a)
    return bodies


def _deco_name(deco: ast.expr) -> str | None:
    if isinstance(deco, ast.Name):
        return deco.id
    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name):
        return deco.func.id
    return None


def _target_wire_name(target: ast.expr, wire_names: Set[str]) -> str | None:
    """Return the wire name being written to, if any."""
    if isinstance(target, ast.Name) and target.id in wire_names:
        return target.id
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        if target.value.id in wire_names and target.attr == "value":
            return target.value.id
    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        if target.value.id in wire_names:
            return target.value.id
    return None


@register_rule
class WriteInsideDerived(Rule):
    code = "PW002"
    default_severity = Severity.ERROR
    description = "wire write inside a derived() body — raises ReactivityError"

    def check(self, ctx: AnalysisContext) -> Iterable[Diagnostic]:
        module = ctx.parsed.python_ast
        if module is None:
            return

        wire_names = ctx.wire_names | ctx.store_names
        if not wire_names:
            return

        for body_node in _derived_bodies(module):
            for sub in ast.walk(body_node):
                targets: list[ast.expr] = []
                if isinstance(sub, ast.Assign):
                    targets = list(sub.targets)
                elif isinstance(sub, ast.AugAssign):
                    targets = [sub.target]
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]

                for t in targets:
                    name = _target_wire_name(t, wire_names)
                    if name is None:
                        continue
                    kind = ctx.kind_of(name) or "wire"
                    yield self.diagnostic(
                        ctx,
                        line=getattr(sub, "lineno", 1),
                        column=getattr(sub, "col_offset", 0),
                        message=(
                            f"write to {kind} {name!r} inside derived() — "
                            "raises ReactivityError at runtime"
                        ),
                        hint=(
                            "Derived values must be pure. Compute the new value "
                            "and return it, or move the write into an effect() "
                            "or event handler."
                        ),
                    )

            # Writes to derived itself via augassign elsewhere
            continue
