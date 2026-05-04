"""Per-file analysis context.

A single pass over the Python AST collects simple name → kind bindings so
individual rules don't each need to re-scan for wire/derived/producer
assignments. This is deliberately lightweight heuristics — not type
inference. The ROADMAP covers real type-flow integration.

Recognized factory kinds: wire, derived, effect, ref, producer. The
former store kinds (writable, readable, store_derived) are gone — the
downstream pywire package no longer ships those names.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from pywire_parser.ast_nodes import ParsedPyWire


class WireKind:
    WIRE = "wire"  # wire(...)
    DERIVED = "derived"  # derived(fn) / @derived
    EFFECT = "effect"  # effect(fn) / @effect
    REF = "ref"  # ref() / ref[Type]()
    PRODUCER = "producer"  # producer(initial, start_fn)


@dataclass
class AnalysisContext:
    """Resolved name kinds for a single .wire file."""

    parsed: ParsedPyWire
    file_path: str
    bindings: Dict[str, str] = field(default_factory=dict)
    # Names assigned via wire(<literal>) — we keep the literal AST so rules
    # can inspect non-serializable initial values (PW001).
    wire_literals: Dict[str, ast.AST] = field(default_factory=dict)

    def kind_of(self, name: str) -> Optional[str]:
        return self.bindings.get(name)

    @property
    def wire_names(self) -> Set[str]:
        return {n for n, k in self.bindings.items() if k == WireKind.WIRE}

    @property
    def derived_names(self) -> Set[str]:
        return {n for n, k in self.bindings.items() if k == WireKind.DERIVED}

    @property
    def producer_names(self) -> Set[str]:
        return {n for n, k in self.bindings.items() if k == WireKind.PRODUCER}


def build_context(parsed: ParsedPyWire, file_path: str) -> AnalysisContext:
    ctx = AnalysisContext(parsed=parsed, file_path=file_path)
    if parsed.python_ast is None:
        return ctx

    for node in parsed.python_ast.body:
        _record_top_level_binding(node, ctx)

    return ctx


def _record_top_level_binding(node: ast.stmt, ctx: AnalysisContext) -> None:
    """Record name → wire-kind bindings from simple top-level assignments."""
    targets: list[ast.expr]
    value: Optional[ast.expr]
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
        value = node.value
    elif isinstance(node, ast.FunctionDef):
        _record_decorated_binding(node, ctx)
        return
    else:
        return

    if value is None:
        return
    kind = _classify_value(value)
    if kind is None:
        return

    for target in targets:
        if isinstance(target, ast.Name):
            ctx.bindings[target.id] = kind
            if kind == WireKind.WIRE and isinstance(value, ast.Call) and value.args:
                ctx.wire_literals[target.id] = value.args[0]


def _record_decorated_binding(node: ast.FunctionDef, ctx: AnalysisContext) -> None:
    for deco in node.decorator_list:
        name = _decorator_name(deco)
        if name == "derived":
            ctx.bindings[node.name] = WireKind.DERIVED
            return
        if name == "effect":
            ctx.bindings[node.name] = WireKind.EFFECT
            return


def _decorator_name(deco: ast.expr) -> Optional[str]:
    if isinstance(deco, ast.Name):
        return deco.id
    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name):
        return deco.func.id
    return None


def _classify_value(value: ast.expr) -> Optional[str]:
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    name: Optional[str] = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Subscript) and isinstance(func.value, ast.Name):
        name = func.value.id  # ref[InputElement]() → "ref"

    if name == "wire":
        return WireKind.WIRE
    if name == "derived":
        return WireKind.DERIVED
    if name == "effect":
        return WireKind.EFFECT
    if name == "ref":
        return WireKind.REF
    if name == "producer":
        return WireKind.PRODUCER
    return None
