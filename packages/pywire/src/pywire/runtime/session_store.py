"""Session store abstraction for PyWire.

Provides a protocol for pluggable session backends and a default
in-memory implementation. Session stores hold serialized page state
snapshots (plain dicts), not live BasePage instances.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session storage backends."""

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session snapshot by ID. Returns None if not found or expired."""
        ...

    async def set(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        """Store a session snapshot. If ttl is provided, the session expires after that many seconds."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete a session."""
        ...

    async def exists(self, session_id: str) -> bool:
        """Check if a session exists and has not expired."""
        ...

    async def touch(self, session_id: str, ttl: Optional[int] = None) -> None:
        """Reset the TTL on a session without updating its data."""
        ...

    async def close(self) -> None:
        """Clean up resources (connections, background tasks, etc.)."""
        ...


class MemorySessionStore:
    """In-memory session store with TTL expiration.

    Suitable for single-worker deployments. Sessions are lost on
    server restart or across workers.
    """

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}
        self._expiry: Dict[str, float] = {}  # session_id -> expiry timestamp
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    def _start_cleanup(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            expired = [
                sid for sid, exp in self._expiry.items() if exp <= now
            ]
            for sid in expired:
                self._data.pop(sid, None)
                self._expiry.pop(sid, None)
            if expired:
                logger.debug("Cleaned up %d expired sessions", len(expired))

    def _is_expired(self, session_id: str) -> bool:
        exp = self._expiry.get(session_id)
        if exp is None:
            return False
        return time.monotonic() > exp

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id not in self._data or self._is_expired(session_id):
            # Clean up expired entry
            self._data.pop(session_id, None)
            self._expiry.pop(session_id, None)
            return None
        return self._data[session_id]

    async def set(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        self._data[session_id] = data
        if ttl is not None:
            self._expiry[session_id] = time.monotonic() + ttl
        self._start_cleanup()

    async def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._expiry.pop(session_id, None)

    async def exists(self, session_id: str) -> bool:
        if session_id not in self._data:
            return False
        if self._is_expired(session_id):
            self._data.pop(session_id, None)
            self._expiry.pop(session_id, None)
            return False
        return True

    async def touch(self, session_id: str, ttl: Optional[int] = None) -> None:
        if session_id in self._data and not self._is_expired(session_id):
            if ttl is not None:
                self._expiry[session_id] = time.monotonic() + ttl

    async def close(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._data.clear()
        self._expiry.clear()
