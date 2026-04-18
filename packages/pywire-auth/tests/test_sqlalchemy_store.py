"""SQLAlchemyAuthStore — persistence across restarts + protocol parity.

Runs against an in-memory SQLite DB for speed. The file-based variant
is exercised via the cross-session test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

try:
    from pywire_auth import LocalIdP, SQLAlchemyAuthStore
except ImportError:  # pragma: no cover - optional dep
    SQLAlchemyAuthStore = None  # type: ignore[assignment,misc]


pytestmark = pytest.mark.skipif(
    SQLAlchemyAuthStore is None,
    reason="sqlalchemy extra not installed",
)


async def _fresh_store(url: str = "sqlite+aiosqlite:///:memory:"):
    store = SQLAlchemyAuthStore(url)
    await store.init_schema()
    return store


@pytest.mark.asyncio
async def test_create_and_get_user() -> None:
    store = await _fresh_store()
    user_id = await store.create_user(
        email="a@b.c", name="Alice", claims={"role": "admin"}
    )
    record = await store.get_user(user_id)
    assert record is not None
    assert record["email"] == "a@b.c"
    assert record["name"] == "Alice"
    assert record["claims"] == {"role": "admin"}
    await store.close()


@pytest.mark.asyncio
async def test_find_by_provider_via_link() -> None:
    store = await _fresh_store()
    user_id = await store.create_user(email="a@b.c")
    await store.link_provider(user_id, "local", "a@b.c", {"email": "a@b.c"})
    found = await store.find_by_provider("local", "a@b.c")
    assert found is not None
    assert found["user_id"] == user_id
    assert found["linked"]["local"]["subject"] == "a@b.c"
    await store.close()


@pytest.mark.asyncio
async def test_password_hash_round_trip() -> None:
    store = await _fresh_store()
    user_id = await store.create_user(email="a@b.c")
    assert await store.get_password_hash(user_id) is None
    await store.set_password_hash(user_id, "hash1")
    assert await store.get_password_hash(user_id) == "hash1"
    await store.set_password_hash(user_id, "hash2")
    assert await store.get_password_hash(user_id) == "hash2"
    await store.close()


@pytest.mark.asyncio
async def test_update_user_merges_extras() -> None:
    store = await _fresh_store()
    user_id = await store.create_user(
        email="a@b.c", name="Alice", claims={"r": "1"}, custom="x"
    )
    await store.update_user(user_id, name="Alicia", foo="y")
    record = await store.get_user(user_id)
    assert record is not None
    assert record["name"] == "Alicia"
    assert record.get("custom") == "x"
    assert record.get("foo") == "y"
    await store.close()


@pytest.mark.asyncio
async def test_link_provider_idempotent() -> None:
    store = await _fresh_store()
    user_id = await store.create_user(email="a@b.c")
    await store.link_provider(user_id, "google", "123", {"email": "a@b.c"})
    # Re-link same (provider, subject) with different claims — should update.
    await store.link_provider(user_id, "google", "123", {"email": "new@b.c"})
    record = await store.get_user(user_id)
    assert record is not None
    assert record["linked"]["google"]["claims"]["email"] == "new@b.c"
    await store.close()


@pytest.mark.asyncio
async def test_localidp_round_trip_with_store() -> None:
    store = await _fresh_store()
    idp = LocalIdP(store=store, secret="s" * 32)
    user_id = await idp.create_user(
        email="a@b.c", password="pw", name="Alice", claims={"role": "admin"}
    )
    principal = await idp.verify_credentials(email="a@b.c", password="pw")
    assert principal is not None
    assert principal.user_id == f"local:{user_id}"
    assert principal.name == "Alice"
    assert principal.has_claim("role", "admin")
    await store.close()


@pytest.mark.asyncio
async def test_persists_across_sessions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "auth.db"
        url = f"sqlite+aiosqlite:///{db}"

        store1 = SQLAlchemyAuthStore(url)
        await store1.init_schema()
        idp1 = LocalIdP(store=store1, secret="s" * 32)
        await idp1.create_user(email="a@b.c", password="pw")
        await store1.close()

        # Fresh store/engine against same DB file.
        store2 = SQLAlchemyAuthStore(url)
        idp2 = LocalIdP(store=store2, secret="s" * 32)
        principal = await idp2.verify_credentials(email="a@b.c", password="pw")
        assert principal is not None
        assert principal.has_claim("email", "a@b.c")
        await store2.close()
