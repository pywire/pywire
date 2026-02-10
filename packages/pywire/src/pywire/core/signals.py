from typing import Any, Callable, Set, Protocol, runtime_checkable
from weakref import WeakSet


class CircularDependencyError(Exception):
    """Raised when a derived value has a circular dependency."""

    pass


class ReactivityError(Exception):
    """Raised on invalid reactivity operations (e.g. writing state in a derived)."""

    pass


_TRACKING_STACK: list = []  # Module-level, sync-only
_BATCH_DEPTH: int = 0
_PENDING_EFFECTS: list["Effect"] = []


@runtime_checkable
class Subscriber(Protocol):
    dependencies: Set[Any]

    def execute(self) -> None: ...


class Derived:
    """Lazy, memoized computed value. Auto-tracks wire dependencies."""

    def __init__(self, fn: Callable[[], Any]):
        self.fn = fn
        self.dependencies: Set[Any] = set()
        self._subscribers: WeakSet[Subscriber] = WeakSet()  # downstream Derived/Effect
        self._cache: Any = None
        self._dirty: bool = True
        self._computing: bool = False

    @property
    def value(self) -> Any:
        if self._computing:
            raise CircularDependencyError(
                f"Circular dependency detected in derived (fn={getattr(self.fn, '__name__', str(self.fn))})"
            )

        if self._dirty:
            # Cleanup old deps
            for dep in list(self.dependencies):
                if hasattr(dep, "_subscribers"):
                    dep._subscribers.discard(self)
            self.dependencies.clear()

            self._computing = True
            _TRACKING_STACK.append(self)
            try:
                self._cache = self.fn()
            finally:
                _TRACKING_STACK.pop()
                self._computing = False
            self._dirty = False

        # Participate in render-context tracking (like wire does)
        self._track_read()

        # Participate in signal tracking (downstream derived/effect)
        if _TRACKING_STACK:
            parent = _TRACKING_STACK[-1]
            self._subscribers.add(parent)
            parent.dependencies.add(self)

        return self._cache

    def peek(self) -> Any:
        """Read value without tracking dependencies."""
        return self._cache

    def execute(self) -> None:
        """Called when an upstream dependency changes."""
        if not self._dirty:
            self._dirty = True
            for sub in list(self._subscribers):
                sub.execute()

    def _track_read(self) -> None:
        """Register with the page's render context if active."""
        from pywire.core.wire import _render_context

        ctx = _render_context.get()
        if not ctx:
            return
        page, region_id = ctx
        register = getattr(page, "_register_wire_read", None)
        if register:
            # We register ourselves as a dependency of the region.
            # When we mark dirty, we don't directly notify the page (yet),
            # but when the page re-renders, it will read our fresh .value.
            # Actually, to trigger a re-render, we MUST notify the page if we change.
            register(self, "value", region_id)

    # Proxy methods for template convenience
    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, format_spec: str) -> str:
        return format(self.value, format_spec)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __repr__(self) -> str:
        return f"derived({self._cache!r}, dirty={self._dirty})"


class Effect:
    """Side-effect that auto-runs when dependencies change."""

    def __init__(self, fn: Callable[[], None]):
        self.fn = fn
        self.dependencies: Set[Any] = set()
        self._disposed: bool = False
        self.execute()  # initial run to capture deps

    def execute(self) -> None:
        if self._disposed:
            return

        if _BATCH_DEPTH > 0:
            if self not in _PENDING_EFFECTS:
                _PENDING_EFFECTS.append(self)
            return

        # Cleanup old deps
        for dep in list(self.dependencies):
            if hasattr(dep, "_subscribers"):
                dep._subscribers.discard(self)
        self.dependencies.clear()

        _TRACKING_STACK.append(self)
        try:
            self.fn()
        finally:
            _TRACKING_STACK.pop()

    def dispose(self) -> None:
        self._disposed = True
        for dep in list(self.dependencies):
            if hasattr(dep, "_subscribers"):
                dep._subscribers.discard(self)
        self.dependencies.clear()


def derived(fn: Callable[[], Any]) -> Derived:
    return Derived(fn)


def effect(fn: Callable[[], None]) -> Effect:
    return Effect(fn)


def start_batch() -> None:
    global _BATCH_DEPTH
    _BATCH_DEPTH += 1


def end_batch() -> None:
    global _BATCH_DEPTH
    _BATCH_DEPTH -= 1
    if _BATCH_DEPTH == 0:
        # Flush pending effects
        # We need to be careful with new effects being added DURING flush
        while _PENDING_EFFECTS:
            eff = _PENDING_EFFECTS.pop(0)
            eff.execute()
