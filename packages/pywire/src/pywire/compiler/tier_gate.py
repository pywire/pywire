"""Deployment-tier gating: the feature -> minimum-tier map, enforced per page.

The map lives here and nowhere else (documented in
``docs/superpowers/tier-capabilities.md`` §Build-time checks):

* ``{$await}`` blocks -> **push** (rejected on stateless)
* ``push_state()`` calls in frontmatter -> **push** (when statically
  visible; matched by call name)
* ``{$auth}``, ``@poll``, ``@event``, forms, uploads, ``bind:``,
  ``.optimistic``, keyed ``{$for}`` and all render-time directives ->
  **plain** (fine on both tiers; not scanned)

There are no server-push hooks in the language today; if one is added,
it joins ``PUSH_FEATURES`` below.

``PyWire(stateless=True)`` is the ceiling assertion. Every compile path
(dev loader, ``pywire build``) funnels through :func:`check_tier`, which
validates the compiled file over its **transitive component closure**
(frontmatter ``.wire`` imports + layout directives). A shared component
with a push feature therefore fails only the pages whose closure
actually uses it, and the error names the page and the chain.

The scan is syntactic and cannot see everything (stated, not pretended):
push triggered inside imported Python helpers or via dynamic dispatch
(``getattr``, computed handler names) is invisible to it. ``create_task()``
alone is deliberately NOT a signal — it is the stateless ``@poll`` pattern.

Framework built-in components (``pywire/components/*.wire``) are exempt:
they ship with the framework and are pinned by the capability matrix —
``FileInput`` calls ``push_state()`` for in-request progress yet works
statelessly (uploads are a plain-tier feature).
"""

import ast
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pywire.compiler.ast_nodes import (
    AwaitAttribute,
    LayoutDirective,
    ParsedPyWire,
    TemplateNode,
)
from pywire.compiler.exceptions import PyWireSyntaxError

_stateless_tier = False

# Built-in framework components, exempt from the gate (see module docstring).
_BUILTIN_COMPONENTS_DIR = Path(__file__).resolve().parent.parent / "components"


def set_stateless_tier(stateless: bool) -> None:
    global _stateless_tier
    _stateless_tier = stateless


def _scan_await(parsed: ParsedPyWire) -> List[Tuple[int, int]]:
    """Line/column of every ``{$await}`` block in the template."""
    hits: List[Tuple[int, int]] = []

    def walk(nodes) -> None:
        for node in nodes:
            if not isinstance(node, TemplateNode):
                continue
            for attr in node.special_attributes:
                if isinstance(attr, AwaitAttribute):
                    hits.append((attr.line, attr.column))
            walk(node.children)

    walk(parsed.template)
    return hits


def _scan_push_state(parsed: ParsedPyWire) -> List[Tuple[int, int]]:
    """Line/column of every statically visible ``push_state()`` call.

    Matches on the call name (``push_state()`` or ``self.push_state()``)
    anywhere in the frontmatter. Reaching it through an imported helper or
    dynamic dispatch is invisible here — documented in the error text.
    """
    hits: List[Tuple[int, int]] = []
    if parsed.python_ast is None:
        return hits
    for node in ast.walk(parsed.python_ast):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: Optional[str] = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name == "push_state":
            hits.append((node.lineno, node.col_offset))
    return hits


#: The feature -> minimum-tier map. Every entry here needs the push tier
#: and is rejected in stateless builds; plain-tier features are not scanned.
PUSH_FEATURES: Dict[str, Callable[[ParsedPyWire], List[Tuple[int, int]]]] = {
    "{$await}": _scan_await,
    "push_state()": _scan_push_state,
}


def check_tier(parsed: ParsedPyWire) -> None:
    """Raise if the file's transitive component closure needs server push.

    Runs on every compile (dev loader + ``pywire build``) when the app
    declared ``stateless=True``. The compiled file is the closure root, so
    for pages the error names the page and the component chain to the
    offending feature.
    """
    if not _stateless_tier:
        return
    if _is_builtin_component(parsed.file_path):
        return

    parser = None
    root = str(Path(parsed.file_path).resolve())
    visited = {root}
    queue: List[Tuple[ParsedPyWire, List[str]]] = [(parsed, [root])]

    while queue:
        current, chain = queue.pop(0)
        for feature, scan in PUSH_FEATURES.items():
            for line, column in scan(current):
                raise PyWireSyntaxError(
                    _error_message(chain, feature),
                    file_path=current.file_path,
                    line=line,
                    column=column,
                )
        for dep in _wire_deps(current):
            key = str(dep)
            if key in visited or _is_builtin_component(dep):
                continue
            visited.add(key)
            if parser is None:
                from pywire.compiler.parser import PyWireParser

                parser = PyWireParser()
            queue.append((parser.parse_file(dep), chain + [key]))


def _error_message(chain: List[str], feature: str) -> str:
    where = " -> ".join(chain)
    return (
        f"{feature} needs server push, which stateless apps "
        "(PyWire(stateless=True)) do not have — the server holds no "
        "timeline between requests. Offending closure: "
        f"{where}. Use @poll for background work, render the slow part "
        "conditionally, or run the stateful tier (remove "
        "stateless=True). This gate is a static scan: push triggered "
        "via imported helpers or dynamic dispatch is invisible to it."
    )


def _wire_deps(parsed: ParsedPyWire) -> List[Path]:
    """Statically resolvable .wire dependencies: layouts + component imports."""
    base = Path(parsed.file_path).resolve().parent
    deps: List[Path] = []

    for directive in parsed.directives:
        if isinstance(directive, LayoutDirective):
            path = Path(directive.layout_path)
            deps.append(path if path.is_absolute() else base / path)

    if parsed.python_ast:
        for node in parsed.python_ast.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                resolved = _resolve_wire_module(node.module, node.level, base)
                if resolved:
                    deps.append(resolved)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = _resolve_wire_module(alias.name, 0, base)
                    if resolved:
                        deps.append(resolved)

    return [dep.resolve() for dep in deps if dep.is_file()]


def _resolve_wire_module(module: str, level: int, base_dir: Path) -> Optional[Path]:
    """Resolve a frontmatter import to a .wire file, if one exists.

    Mirrors Python import semantics closely enough for the gate: relative
    imports anchor at the importing file's directory; absolute module paths
    (``components.SlowPanel``) are probed against the base directory and its
    ancestors. Imports of real Python packages (``pywire.*`` etc.) resolve to
    nothing here and are skipped — the framework's built-in components are
    loaded at runtime and are exempt anyway.
    """
    if module.split(".")[0] == "pywire":
        return None
    rel = module.replace(".", "/") + ".wire"
    start = base_dir
    for _ in range(max(level - 1, 0)):
        start = start.parent
    current = start
    while True:
        candidate = current / rel
        if candidate.is_file():
            return candidate
        if current == current.parent:
            return None
        current = current.parent


def _is_builtin_component(path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(_BUILTIN_COMPONENTS_DIR)
    except (OSError, ValueError):
        return False
