"""Svelte-inspired reactive stores for PyWire.

Stores provide a subscription-based API on top of the Wire reactivity system.
They integrate with render context tracking and the signals system (Derived/Effect).

- writable(value) -- read/write store
- readable(value, start_fn) -- read-only store with producer
- store_derived(stores, fn) -- derived store from one or more source stores
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Set, Union

from pywire.core.signals import Derived, Effect
from pywire.core.wire import WirePrimitive


class WritableStore:
    """A reactive store with read/write access."""

    def __init__(self, initial: Any) -> None:
        self._wire = WirePrimitive(initial)
        self._subscribers: Set[Callable] = set()

    @property
    def value(self) -> Any:
        self._wire._track_read()
        return self._wire._value

    @value.setter
    def value(self, new_val: Any) -> None:
        self._wire.value = new_val  # triggers _notify_write internally
        self._notify_subscribers()

    def set(self, value: Any) -> None:
        """Set the store to a new value."""
        self.value = value

    def update(self, fn: Callable[[Any], Any]) -> None:
        """Update the value using a function that receives the current value."""
        self.value = fn(self._wire._value)

    def subscribe(self, callback: Callable[[Any], Any]) -> Callable[[], None]:
        """Subscribe to value changes. Callback is called immediately with the current value.

        Returns an unsubscribe function.
        """
        self._subscribers.add(callback)
        try:
            callback(self._wire._value)  # Svelte convention: call immediately
        except Exception:
            pass  # Don't let subscriber errors break the subscription

        def unsubscribe() -> None:
            self._subscribers.discard(callback)

        return unsubscribe

    def _notify_subscribers(self) -> None:
        for cb in list(self._subscribers):
            try:
                cb(self._wire._value)
            except Exception:
                pass  # Don't let one subscriber break others

    def __repr__(self) -> str:
        return f"WritableStore({self._wire._value!r})"


class ReadableStore:
    """A reactive store with read-only access. Value is set by a start function."""

    def __init__(
        self, initial: Any, start_fn: Optional[Callable[..., Any]] = None
    ) -> None:
        self._wire = WirePrimitive(initial)
        self._subscribers: Set[Callable] = set()
        self._start_fn = start_fn
        self._stop_fn: Optional[Callable[[], None]] = None

    @property
    def value(self) -> Any:
        self._wire._track_read()
        return self._wire._value

    def subscribe(self, callback: Callable[[Any], Any]) -> Callable[[], None]:
        """Subscribe to value changes. Starts the producer on first subscriber.

        Returns an unsubscribe function.
        """
        # Start producer on first subscriber
        if not self._subscribers and self._start_fn:

            def setter(val: Any) -> None:
                self._wire.value = val
                for cb in list(self._subscribers):
                    cb(val)

            result = self._start_fn(setter)
            if callable(result):
                self._stop_fn = result

        self._subscribers.add(callback)
        callback(self._wire._value)  # Svelte convention: call immediately

        def unsubscribe() -> None:
            self._subscribers.discard(callback)
            # Stop producer when last subscriber leaves
            if not self._subscribers and self._stop_fn:
                self._stop_fn()
                self._stop_fn = None

        return unsubscribe

    def __repr__(self) -> str:
        return f"ReadableStore({self._wire._value!r})"


class DerivedStore:
    """A store derived from one or more source stores."""

    def __init__(self, stores: Union[list, tuple], fn: Callable[..., Any]) -> None:
        self._stores = stores
        self._fn = fn
        self._derived = Derived(lambda: fn(*[s.value for s in self._stores]))

    @property
    def value(self) -> Any:
        return self._derived.value

    def subscribe(self, callback: Callable[[Any], Any]) -> Callable[[], None]:
        """Subscribe to value changes. Uses Effect for auto-tracking.

        Returns an unsubscribe function.
        """

        def run() -> None:
            callback(self.value)

        eff = Effect(run)

        def unsubscribe() -> None:
            eff.dispose()

        return unsubscribe

    def __repr__(self) -> str:
        return f"DerivedStore({self._derived._cache!r})"


def writable(initial_value: Any) -> WritableStore:
    """Create a writable store with the given initial value."""
    return WritableStore(initial_value)


def readable(
    initial_value: Any, start_fn: Optional[Callable[..., Any]] = None
) -> ReadableStore:
    """Create a readable store with the given initial value and optional start function."""
    return ReadableStore(initial_value, start_fn)


def store_derived(
    stores: Union[Any, list, tuple], fn: Callable[..., Any]
) -> DerivedStore:
    """Create a derived store from one or more source stores.

    Args:
        stores: A single store or list/tuple of stores to derive from.
        fn: A function that receives the current values of all source stores
            and returns the derived value.
    """
    if not isinstance(stores, (list, tuple)):
        stores = [stores]
    return DerivedStore(stores, fn)
