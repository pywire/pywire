"""In-process attempt limiting for password sign-in and registration."""

from __future__ import annotations

import time
from typing import Dict, Tuple


class Throttle:
    """At most ``limit`` attempts per key in any ``window`` seconds.

    Keys are whatever the caller counts by: the client address, the email
    tried. Counts live in this process, so each worker limits on its own;
    that still turns an online password guess from thousands per second
    into a handful per minute.
    """

    def __init__(
        self, limit: int = 20, window: float = 300.0, max_keys: int = 100_000
    ) -> None:
        if limit < 1 or window <= 0:
            raise ValueError("Throttle needs limit >= 1 and window > 0")
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        # key -> (window start, attempts in it)
        self._counts: Dict[str, Tuple[float, int]] = {}

    def blocked(self, *keys: str) -> bool:
        """True when any key has used up its attempts for now."""
        now = time.monotonic()
        for key in keys:
            start, count = self._counts.get(key, (now, 0))
            if now - start < self.window and count >= self.limit:
                return True
        return False

    def hit(self, *keys: str) -> None:
        """Count one attempt against every key."""
        now = time.monotonic()
        if len(self._counts) >= self.max_keys:
            self._prune(now)
        for key in keys:
            start, count = self._counts.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            self._counts[key] = (start, count + 1)

    def reset(self, *keys: str) -> None:
        for key in keys:
            self._counts.pop(key, None)

    def _prune(self, now: float) -> None:
        for key, (start, _count) in list(self._counts.items()):
            if now - start >= self.window:
                del self._counts[key]
        # Still full: forget the oldest windows rather than grow without bound.
        excess = len(self._counts) - self.max_keys // 2
        if excess > 0:
            for key in sorted(self._counts, key=lambda k: self._counts[k][0])[:excess]:
                del self._counts[key]
