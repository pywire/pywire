"""SessionPersister: at most one session-store write per window, latest state wins."""

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from pywire.runtime.session_persist import SessionPersister


class RecordingStore:
    def __init__(self) -> None:
        self.writes: List[Dict[str, Any]] = []

    async def set(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        self.writes.append({"session_id": session_id, **data["attrs"]})


class Page:
    def __init__(self, count: int) -> None:
        self.count = count
        self.errors: Dict[str, Any] = {}
        self.loading: Dict[str, Any] = {}


def make_persister(interval: float) -> tuple[SessionPersister, RecordingStore]:
    store = RecordingStore()
    app = MagicMock()
    app.session_store = store
    app.session_ttl = 60
    app.session_warn_size = 0
    app.session_persist_interval = interval
    return SessionPersister(app), store


async def settle_tasks() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_burst_collapses_to_leading_and_trailing_write() -> None:
    persister, store = make_persister(0.05)
    page = Page(0)
    for i in range(100):
        page.count = i
        persister.schedule("s", page)
        await asyncio.sleep(0)

    assert [w["count"] for w in store.writes] == [0]
    await asyncio.sleep(0.08)
    assert [w["count"] for w in store.writes] == [0, 99]


@pytest.mark.asyncio
async def test_quiet_session_writes_every_event() -> None:
    persister, store = make_persister(0.01)
    for i in range(3):
        persister.schedule("s", Page(i))
        await asyncio.sleep(0.03)

    assert [w["count"] for w in store.writes] == [0, 1, 2]


@pytest.mark.asyncio
async def test_sessions_are_throttled_independently() -> None:
    persister, store = make_persister(60)
    persister.schedule("a", Page(1))
    persister.schedule("b", Page(2))
    await settle_tasks()

    assert sorted((w["session_id"], w["count"]) for w in store.writes) == [
        ("a", 1),
        ("b", 2),
    ]
    await persister.drain()
    persister.flush("a")
    persister.flush("b")
    await settle_tasks()


@pytest.mark.asyncio
async def test_flush_writes_pending_state_before_the_window_ends() -> None:
    persister, store = make_persister(60)
    persister.schedule("s", Page(1))
    await settle_tasks()
    persister.schedule("s", Page(2))
    await settle_tasks()
    assert [w["count"] for w in store.writes] == [1]

    persister.flush("s")
    await settle_tasks()
    assert [w["count"] for w in store.writes] == [1, 2]
    persister.flush("s")
    await settle_tasks()


@pytest.mark.asyncio
async def test_settle_and_drain_write_pending_state_now() -> None:
    persister, store = make_persister(60)
    persister.schedule("s", Page(1))
    await settle_tasks()
    persister.schedule("s", Page(2))

    await persister.settle("s")
    assert [w["count"] for w in store.writes] == [1, 2]

    persister.schedule("s", Page(3))
    await persister.drain()
    assert [w["count"] for w in store.writes] == [1, 2, 3]
    await persister.settle("unknown")  # no-op
    persister.flush("s")
    await settle_tasks()


@pytest.mark.asyncio
async def test_failed_write_is_logged_and_the_session_keeps_persisting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    persister, store = make_persister(0.01)
    calls = 0
    real_set = store.set

    async def flaky_set(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("store down")
        await real_set(*args, **kwargs)

    store.set = flaky_set  # type: ignore[method-assign]
    persister.schedule("s", Page(1))
    await asyncio.sleep(0.03)
    persister.schedule("s", Page(2))
    await asyncio.sleep(0.03)

    assert "Failed to persist session s" in caplog.text
    assert [w["count"] for w in store.writes] == [2]
