"""A shared counter saved to slow storage: where races come from.

``SlowStore`` stands in for a database or an HTTP API: every call awaits.
While a handler awaits, the event loop runs other users' handlers, so a
read-modify-write that spans an ``await`` can lose updates.
"""

from __future__ import annotations

import asyncio

from pywire import wire


class SlowStore:
    def __init__(self) -> None:
        self._value = 0

    async def get(self) -> int:
        await asyncio.sleep(0.02)
        return self._value

    async def put(self, value: int) -> None:
        await asyncio.sleep(0.02)
        self._value = value


store = SlowStore()

# What the pages show. The store is the source of truth; this wire is the
# live view of it that every page renders.
saved = wire(0)

_lock = asyncio.Lock()


async def add_unsafe() -> None:
    # Two users can both read 5 here, both write 6, and one click is lost.
    current = await store.get()
    await store.put(current + 1)
    saved.value = await store.get()


async def add_locked() -> None:
    # One read-modify-write at a time. In a real app, prefer the storage's
    # own atomic update (UPDATE counters SET n = n + 1) or a transaction;
    # an asyncio.Lock only covers one process.
    async with _lock:
        current = await store.get()
        await store.put(current + 1)
        saved.value = current + 1


async def reset() -> None:
    async with _lock:
        await store.put(0)
        saved.value = 0
