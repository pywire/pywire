"""Realtime auth updates across live sessions.

Transport handlers (WS, HTTP long-poll, WebTransport) subscribe to an
``AuthChannel`` keyed by ``user_id`` and translate events into per-transport
push messages. The default ``MemoryAuthChannel`` is in-process; multi-worker
deployments plug in a ``RedisAuthChannel`` from ``pywire-auth[redis]``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Protocol,
    Set,
    Type,
    runtime_checkable,
)

from pywire.auth.principal import Claim, ClaimsPrincipal


@dataclass
class AuthEvent:
    """An auth-state change pushed to live sessions."""

    user_id: str
    kind: str  # "update" | "revoke"
    claims: Optional[List[Claim]] = None
    principal: Optional[ClaimsPrincipal] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthChannel(Protocol):
    """Structural interface for auth event fan-out."""

    async def update_principal(
        self,
        user_id: str,
        *,
        claims: Optional[List[Claim]] = None,
        principal: Optional[ClaimsPrincipal] = None,
    ) -> None: ...

    async def revoke(self, user_id: str) -> None: ...

    def subscribe(self, user_id: str) -> "AuthSubscription": ...


class AuthSubscription:
    """Async context manager + iterator over AuthEvents for one user_id."""

    def __init__(self, channel: "MemoryAuthChannel", user_id: str) -> None:
        self._channel = channel
        self._user_id = user_id
        self._queue: asyncio.Queue[AuthEvent] = asyncio.Queue()

    async def __aenter__(self) -> "AuthSubscription":
        self._channel._subscribers.setdefault(self._user_id, set()).add(self._queue)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        subs = self._channel._subscribers.get(self._user_id)
        if subs is not None:
            subs.discard(self._queue)
            if not subs:
                del self._channel._subscribers[self._user_id]

    def __aiter__(self) -> AsyncIterator[AuthEvent]:
        return self

    async def __anext__(self) -> AuthEvent:
        return await self._queue.get()


class MemoryAuthChannel:
    """In-process AuthChannel implementation.

    Works for single-worker deployments. Multi-worker apps should swap in
    a cross-process backend (``RedisAuthChannel`` from ``pywire-auth[redis]``).
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue[AuthEvent]]] = {}

    async def update_principal(
        self,
        user_id: str,
        *,
        claims: Optional[List[Claim]] = None,
        principal: Optional[ClaimsPrincipal] = None,
    ) -> None:
        event = AuthEvent(
            user_id=user_id, kind="update", claims=claims, principal=principal
        )
        self._dispatch(user_id, event)

    async def revoke(self, user_id: str) -> None:
        self._dispatch(user_id, AuthEvent(user_id=user_id, kind="revoke"))

    def subscribe(self, user_id: str) -> AuthSubscription:
        return AuthSubscription(self, user_id)

    def _dispatch(self, user_id: str, event: AuthEvent) -> None:
        for q in list(self._subscribers.get(user_id, ())):
            q.put_nowait(event)
