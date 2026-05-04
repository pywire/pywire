"""Producer: reactive primitive backed by an external source.

A `producer(initial, start_fn)` wraps an external data source (timer,
websocket, polling API, file watch) as a reactive value. The producer
is lazy: `start_fn` runs on the first `.value` read or `.subscribe()`
call, and continues running until `.dispose()` is called.

The `start_fn` receives a `set_value(val)` callback to push new values.
It may optionally return a no-arg cleanup function that runs on
`.dispose()`.

Producers participate in the same render-context tracking as `wire()`,
so accessing `producer.value` inside a `.wire` template makes the
region re-render whenever the producer pushes a new value.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from pywire.core.wire import WireBase


class Producer(WireBase):
    """External-source reactive primitive with lazy start + manual stop."""

    def __init__(
        self,
        initial: Any,
        start_fn: Optional[Callable[[Callable[[Any], None]], Any]] = None,
    ) -> None:
        super().__init__()
        self._value = initial
        self._start_fn = start_fn
        self._stop_fn: Optional[Callable[[], None]] = None
        self._started = False

    def _maybe_start(self) -> None:
        if self._started or self._start_fn is None:
            return
        self._started = True

        def setter(val: Any) -> None:
            if self._value == val:
                return
            self._value = val
            self._notify_write()

        result = self._start_fn(setter)
        if callable(result):
            self._stop_fn = result  # type: ignore[assignment]

    @property
    def value(self) -> Any:
        self._maybe_start()
        self._track_read()
        return self._value

    def peek(self) -> Any:
        return self._value

    def dispose(self) -> None:
        """Stop the producer. Calls the cleanup fn returned by start_fn, if any."""
        if self._stop_fn is not None:
            try:
                self._stop_fn()
            finally:
                self._stop_fn = None
        self._started = False

    def __repr__(self) -> str:
        return f"Producer({self._value!r})"

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)

    def __bool__(self) -> bool:
        return bool(self.value)


def producer(
    initial: Any,
    start_fn: Optional[Callable[[Callable[[Any], None]], Any]] = None,
) -> Producer:
    """Create a producer-backed reactive value.

    Args:
        initial: The starting value.
        start_fn: Called on first read with a `set_value(val)` callback.
            May return a no-arg cleanup function that runs on `.dispose()`.
    """
    return Producer(initial, start_fn)
