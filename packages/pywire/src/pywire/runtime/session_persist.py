"""Throttled, coalescing writes of live page state to the session store.

Every interactive transport persists after each event so a reconnect (or
another worker) can restore the page. A snapshot is O(page state), so writing
one per event caps a list page at a few hundred events/s per core even when
the update itself is tiny. ``SessionPersister`` writes at most once per
``PyWire.session_persist_interval`` seconds per session: the first change
after a quiet period is written straight away, and changes inside the window
collapse into one trailing write of the latest state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict

from pywire.runtime.session_serializer import page_state_key, snapshot_page_state

if TYPE_CHECKING:
    from pywire.runtime.page import BasePage

logger = logging.getLogger(__name__)


class SessionPersister:
    def __init__(self, app: Any) -> None:
        self._app = app
        self._pending: Dict[str, BasePage] = {}
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._wake: Dict[str, asyncio.Event] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def schedule(self, session_id: str, page: BasePage) -> None:
        """Mark ``page`` as the latest state of ``session_id``."""
        self._pending[session_id] = page
        if session_id not in self._tasks:
            self._wake[session_id] = asyncio.Event()
            self._locks[session_id] = asyncio.Lock()
            self._tasks[session_id] = asyncio.create_task(self._run(session_id))

    def flush(self, session_id: str) -> None:
        """Write pending state now instead of at the end of the window."""
        wake = self._wake.get(session_id)
        if wake is not None:
            wake.set()

    async def settle(self, session_id: str) -> None:
        """Write pending state now and wait for it, e.g. before a reconnect reads it."""
        lock = self._locks.get(session_id)
        if lock is not None:
            await self._write_pending(session_id, lock)

    async def drain(self) -> None:
        """Write every session's pending state (server shutdown)."""
        for session_id in list(self._pending):
            await self.settle(session_id)

    async def _run(self, session_id: str) -> None:
        wake = self._wake[session_id]
        lock = self._locks[session_id]
        try:
            while session_id in self._pending:
                wake.clear()
                await self._write_pending(session_id, lock)
                try:
                    await asyncio.wait_for(
                        wake.wait(), self._app.session_persist_interval
                    )
                except TimeoutError:
                    pass
        finally:
            self._tasks.pop(session_id, None)
            self._wake.pop(session_id, None)
            self._locks.pop(session_id, None)

    async def _write_pending(self, session_id: str, lock: asyncio.Lock) -> None:
        async with lock:
            page = self._pending.pop(session_id, None)
            if page is None:
                return
            try:
                snapshot = snapshot_page_state(
                    page, warn_size=self._app.session_warn_size
                )
                await self._app.session_store.set(
                    page_state_key(session_id, page),
                    snapshot,
                    ttl=self._app.session_ttl,
                )
            except Exception:
                logger.warning(
                    "Failed to persist session %s", session_id, exc_info=True
                )
