"""PW001 — ``wire()`` assigned a non-serializable initial value.

v1 detects AST-level literal/call patterns that can never round-trip
through the session serializer. It does not yet follow flow — a
``wire(None)`` later assigned a class instance still passes. See the
ROADMAP for type-flow plans.
"""

from __future__ import annotations

import ast
from typing import Iterable

from pywire_parser.analysis.context import AnalysisContext
from pywire_parser.analysis.diagnostics import Diagnostic, Severity
from pywire_parser.analysis.registry import register_rule
from pywire_parser.analysis.rules.base import Rule


# Call-expression names whose instances are known to be non-serializable.
# These are heuristic hits on ``wire(SomeClass(...))`` patterns.
_NON_SERIALIZABLE_NAMES = frozenset(
    {
        # stdlib / common infra
        "datetime",
        "date",
        "time",
        "timedelta",
        "Path",
        "PurePath",
        "Lock",
        "RLock",
        "Event",
        "Semaphore",
        "Queue",
        "BytesIO",
        "StringIO",
        # network / DB / IO
        "Connection",
        "Client",
        "Session",
        "Engine",
        "Pool",
        "Socket",
        "Stream",
    }
)


_NON_SERIALIZABLE_SUFFIXES = (
    "Session",
    "Connection",
    "Client",
    "Engine",
    "Pool",
    "Lock",
    "Queue",
    "Socket",
    "Stream",
)


def _is_serializable_literal(node: ast.AST) -> bool:
    """Return True for AST literals that will round-trip through msgpack."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (type(None), bool, int, float, str, bytes))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_serializable_literal(el) for el in node.elts)
    if isinstance(node, ast.Dict):
        keys_ok = all(
            k is not None
            and isinstance(k, ast.Constant)
            and isinstance(k.value, (str, int))
            for k in node.keys
        )
        values_ok = all(_is_serializable_literal(v) for v in node.values)
        return keys_ok and values_ok
    return False


def _lambda_or_callable(node: ast.AST) -> bool:
    return isinstance(node, (ast.Lambda,))


def _call_names(node: ast.Call) -> list[str]:
    """All candidate names for the callee — for ``a.b.c()`` returns ['a','c']."""
    func = node.func
    names: list[str] = []
    if isinstance(func, ast.Name):
        names.append(func.id)
    elif isinstance(func, ast.Attribute):
        names.append(func.attr)
        base = func.value
        while isinstance(base, ast.Attribute):
            base = base.value
        if isinstance(base, ast.Name):
            names.append(base.id)
    return names


def _classify_wire_arg(arg: ast.AST) -> tuple[str, str] | None:
    """Return (class_name, reason) if ``arg`` is clearly non-serializable."""
    if _is_serializable_literal(arg):
        return None
    if _lambda_or_callable(arg):
        return ("<lambda>", "callables cannot be serialized")
    if isinstance(arg, ast.Call):
        names = _call_names(arg)
        for name in names:
            if name in _NON_SERIALIZABLE_NAMES:
                return (name, f"{name} instances are not msgpack-serializable")
        for name in names:
            if any(name.endswith(sfx) for sfx in _NON_SERIALIZABLE_SUFFIXES):
                return (
                    name,
                    f"{name} looks like a resource handle (suffix match) — "
                    "session serializer will skip it",
                )
    return None


@register_rule
class NonSerializableWireLiteral(Rule):
    code = "PW001"
    default_severity = Severity.WARNING
    description = "wire() assigned a non-serializable initial value"

    def check(self, ctx: AnalysisContext) -> Iterable[Diagnostic]:
        if ctx.parsed.python_ast is None:
            return

        for name, arg in ctx.wire_literals.items():
            verdict = _classify_wire_arg(arg)
            if verdict is None:
                continue
            cls, reason = verdict
            yield self.diagnostic(
                ctx,
                line=getattr(arg, "lineno", 1),
                column=getattr(arg, "col_offset", 0),
                message=(
                    f"wire variable {name!r} has a non-serializable initial value "
                    f"({cls}); {reason}"
                ),
                hint=(
                    "Sessions using this page will not persist this value across "
                    "reconnects or workers. Store a serializable seed and derive "
                    "the resource lazily in a handler."
                ),
            )
