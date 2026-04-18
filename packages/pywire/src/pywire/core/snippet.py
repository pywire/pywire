"""Render-region primitives: snippets, children, and the head teleport buffer.

This module defines the runtime substrate for PyWire's render-region system:

- ``RenderUnit``: the unified reactive rendering primitive underlying both
  named user snippets and anonymous framework-generated regions. Holds a
  stable id, an async render function, and memoization state (last args,
  last html, captured wire versions).
- ``Snippet``: the first-class value passed as a component prop. Wraps a
  ``RenderUnit`` and a tuple of already-bound args (when a snippet is
  captured as a value the outer closure's args are fixed).
- ``SnippetType``: runtime descriptor for ``Snippet[A, B]`` annotations,
  emitted by ``Snippet.__class_getitem__``. Used by props validation and
  future static-analysis tooling.
- ``Child`` / ``Children``: validation sentinels for the protected
  ``children`` prop. ``Child`` expects exactly one child element;
  ``Children[min=..., max=..., n=...]`` expects a list with count
  constraints.
- ``HeadBuffer``: page-scoped accumulator for ``{$head}...{/head}``
  contributions, with last-title-wins dedup.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, List, Optional, Tuple


_UNSET: Any = object()  # sentinel for "no cached value yet"

# Matches a <title>...</title> tag at any position (case-insensitive, single-line).
_TITLE_RE = re.compile(r"<title\b[^>]*>.*?</title\s*>", re.IGNORECASE | re.DOTALL)


class RenderUnit:
    """Unified reactive render scope.

    Backs both user-defined snippets and framework-generated anonymous
    regions. Provides memoization via last-args equality plus wire
    version tracking (wire tracking lives in ``BasePage``; ``RenderUnit``
    holds the cached output keyed by args).
    """

    __slots__ = (
        "unit_id",
        "name",
        "func",
        "scope",
        "_prev_args",
        "_prev_html",
    )

    def __init__(
        self,
        unit_id: str,
        func: Callable[..., Awaitable[str]],
        name: Optional[str] = None,
        scope: Optional[Any] = None,
    ) -> None:
        self.unit_id = unit_id
        self.name = name
        self.func = func
        self.scope = scope
        self._prev_args: Any = _UNSET
        self._prev_html: Optional[str] = None

    async def render(self, *args: Any) -> str:
        """Run the render function. Memoization check is the caller's
        responsibility (``BasePage._invoke_render``) so it can coordinate
        with the wire-dirty tracker."""
        return await self.func(*args)

    def cached(self, args: Tuple[Any, ...]) -> Optional[str]:
        """Return cached html if prior args compare equal to ``args``,
        else None. Uses Python ``==`` for deep equality; falls back to
        identity if ``__eq__`` raises."""
        if self._prev_args is _UNSET:
            return None
        try:
            if self._prev_args == args:
                return self._prev_html
        except Exception:
            if self._prev_args is args:
                return self._prev_html
        return None

    def store(self, args: Tuple[Any, ...], html: str) -> None:
        self._prev_args = args
        self._prev_html = html

    def invalidate(self) -> None:
        """Clear the memo cache. Called when a captured wire flips."""
        self._prev_args = _UNSET
        self._prev_html = None


class SnippetType:
    """Runtime descriptor for ``Snippet[A, B]`` annotations."""

    __slots__ = ("arg_types",)

    def __init__(self, arg_types: Tuple[Any, ...]) -> None:
        self.arg_types = arg_types

    def __repr__(self) -> str:
        names = ", ".join(getattr(t, "__name__", repr(t)) for t in self.arg_types)
        return f"Snippet[{names}]"


class Snippet:
    """First-class snippet value.

    Wraps a ``RenderUnit`` plus optional bound args. Passed as a
    component prop (``some_comp_prop={my_snippet}``) or stored as a
    value for later invocation.
    """

    __slots__ = ("unit", "bound_args")

    def __init__(self, unit: RenderUnit, bound_args: Tuple[Any, ...] = ()) -> None:
        self.unit = unit
        self.bound_args = bound_args

    async def render(self, *args: Any) -> str:
        return await self.unit.render(*self.bound_args, *args)

    # Enable `await snippet(*args)` shorthand by making it directly callable.
    def __call__(self, *args: Any) -> Awaitable[str]:
        return self.unit.render(*self.bound_args, *args)

    def __class_getitem__(cls, params: Any) -> SnippetType:
        if not isinstance(params, tuple):
            params = (params,)
        return SnippetType(params)

    def __repr__(self) -> str:
        name = self.unit.name or "<anonymous>"
        return f"Snippet({name})"


class Child:
    """Sentinel: the ``children`` prop must be exactly one child element.

    Used as a type annotation in ``@props``:

        children: Child
    """

    def __class_getitem__(cls, params: Any) -> Any:
        # Accept but ignore params — included so `Child[...]` parses if a
        # user tries it (e.g. by analogy with Children); canonical form
        # is bare `Child`.
        del params
        return cls


class ChildrenType:
    """Runtime descriptor for ``Children[...]`` constraints."""

    __slots__ = ("min", "max", "n")

    def __init__(
        self,
        min: int = 0,
        max: Optional[int] = None,
        n: Optional[int] = None,
    ) -> None:
        if n is not None and (min != 0 or max is not None):
            raise ValueError("Children: specify either n= or min/max, not both")
        self.min = min
        self.max = max
        self.n = n

    def validate_count(self, count: int) -> None:
        """Raise ``ValueError`` if ``count`` violates the constraint."""
        if self.n is not None:
            if count != self.n:
                raise ValueError(
                    f"Expected exactly {self.n} children, got {count}"
                )
            return
        if count < self.min:
            raise ValueError(
                f"Expected at least {self.min} children, got {count}"
            )
        if self.max is not None and count > self.max:
            raise ValueError(
                f"Expected at most {self.max} children, got {count}"
            )

    def __repr__(self) -> str:
        if self.n is not None:
            return f"Children[n={self.n}]"
        parts = [f"min={self.min}"]
        if self.max is not None:
            parts.append(f"max={self.max}")
        return f"Children[{', '.join(parts)}]"


class Children:
    """Sentinel: the ``children`` prop is a list of child snippets.

    Usage:

        children: Children                    # 0..N
        children: Children[min=1]             # 1..N
        children: Children[max=5]             # 0..5
        children: Children[min=1, max=5]      # 1..5
        children: Children[n=3]               # exactly 3
        children: Children[3]                 # sugar: exactly 3
    """

    def __class_getitem__(cls, params: Any) -> ChildrenType:
        # Support a handful of invocation shapes:
        #   Children[3]                   → n=3
        #   Children[slice(min, max)]     → rare; fallthrough
        #   Children[min=1, max=5]        → NamedTupleLike (not supported as
        #                                   __class_getitem__ doesn't accept
        #                                   kwargs) — use helper below instead.
        if isinstance(params, int):
            return ChildrenType(n=params)
        if isinstance(params, dict):
            return ChildrenType(**params)
        # Allow Children[ChildrenType(...)] passthrough
        if isinstance(params, ChildrenType):
            return params
        raise TypeError(
            "Children[...] accepts an int (exact count), a dict of "
            "{min, max, n}, or a pre-built ChildrenType. For kwargs use "
            "Children.of(min=..., max=..., n=...)."
        )

    @classmethod
    def of(
        cls,
        *,
        min: int = 0,
        max: Optional[int] = None,
        n: Optional[int] = None,
    ) -> ChildrenType:
        """Named-argument helper: ``children: Children.of(min=1, max=5)``."""
        return ChildrenType(min=min, max=max, n=n)


class HeadBuffer:
    """Page-scoped accumulator for ``{$head}`` contributions.

    Contributions are appended in render order; on ``flush``, the last
    ``<title>`` tag observed wins (earlier ``<title>`` tags are dropped).
    Non-title content is preserved in the order it was contributed.
    """

    __slots__ = ("_contributions", "_title")

    def __init__(self) -> None:
        self._contributions: List[str] = []
        self._title: Optional[str] = None

    def contribute(self, html: str) -> None:
        # Extract the last <title> in this contribution, track it as the
        # winning title, and strip any <title> tags from the contribution
        # itself so later flush can re-insert the winner once.
        titles = _TITLE_RE.findall(html)
        if titles:
            self._title = titles[-1]
            html = _TITLE_RE.sub("", html)
        self._contributions.append(html)

    def flush(self) -> str:
        parts: List[str] = []
        if self._title is not None:
            parts.append(self._title)
        parts.extend(self._contributions)
        return "".join(parts)

    def clear(self) -> None:
        self._contributions.clear()
        self._title = None

    def __bool__(self) -> bool:
        return bool(self._contributions) or self._title is not None
