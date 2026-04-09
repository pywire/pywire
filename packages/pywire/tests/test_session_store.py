"""Tests for the session store abstraction."""

import time

import pytest

from pywire.runtime.session_store import MemorySessionStore


@pytest.fixture
def store():
    return MemorySessionStore()


class TestMemorySessionStore:
    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        await store.set("s1", {"count": 5}, ttl=60)
        result = await store.get("s1")
        assert result == {"count": 5}

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        result = await store.get("nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self, store):
        assert not await store.exists("s1")
        await store.set("s1", {"x": 1}, ttl=60)
        assert await store.exists("s1")

    @pytest.mark.asyncio
    async def test_delete(self, store):
        await store.set("s1", {"x": 1}, ttl=60)
        await store.delete("s1")
        assert not await store.exists("s1")
        assert await store.get("s1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, store):
        await store.delete("nope")  # Should not raise

    @pytest.mark.asyncio
    async def test_overwrite(self, store):
        await store.set("s1", {"v": 1}, ttl=60)
        await store.set("s1", {"v": 2}, ttl=60)
        result = await store.get("s1")
        assert result == {"v": 2}

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, store):
        # Use a very short TTL
        await store.set("s1", {"x": 1}, ttl=1)
        assert await store.exists("s1")

        # Manually expire by adjusting the expiry timestamp
        store._expiry["s1"] = time.monotonic() - 1
        assert not await store.exists("s1")
        assert await store.get("s1") is None

    @pytest.mark.asyncio
    async def test_touch_extends_ttl(self, store):
        await store.set("s1", {"x": 1}, ttl=10)
        original_expiry = store._expiry["s1"]

        await store.touch("s1", ttl=100)
        new_expiry = store._expiry["s1"]
        assert new_expiry > original_expiry

    @pytest.mark.asyncio
    async def test_touch_nonexistent_is_noop(self, store):
        await store.touch("nope", ttl=60)  # Should not raise

    @pytest.mark.asyncio
    async def test_touch_expired_is_noop(self, store):
        await store.set("s1", {"x": 1}, ttl=1)
        store._expiry["s1"] = time.monotonic() - 1  # Force expire
        await store.touch("s1", ttl=100)
        # Should still be expired since touch checks expiry first
        assert not await store.exists("s1")

    @pytest.mark.asyncio
    async def test_no_ttl_means_no_expiry(self, store):
        await store.set("s1", {"x": 1})  # No TTL
        assert "s1" not in store._expiry
        assert await store.exists("s1")

    @pytest.mark.asyncio
    async def test_close_clears_data(self, store):
        await store.set("s1", {"x": 1}, ttl=60)
        await store.close()
        assert len(store._data) == 0
        assert len(store._expiry) == 0

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, store):
        await store.set("s1", {"page": "home"}, ttl=60)
        await store.set("s2", {"page": "about"}, ttl=60)
        await store.set("s3", {"page": "contact"}, ttl=60)

        assert await store.get("s1") == {"page": "home"}
        assert await store.get("s2") == {"page": "about"}
        assert await store.get("s3") == {"page": "contact"}

        await store.delete("s2")
        assert await store.exists("s1")
        assert not await store.exists("s2")
        assert await store.exists("s3")

    @pytest.mark.asyncio
    async def test_complex_data(self, store):
        data = {
            "attrs": {"count": 5, "items": [1, 2, 3], "name": "test"},
            "wire_tags": {"count": "primitive", "items": "list"},
            "errors": {},
            "loading": {"fetch": True},
        }
        await store.set("s1", data, ttl=60)
        result = await store.get("s1")
        assert result == data
