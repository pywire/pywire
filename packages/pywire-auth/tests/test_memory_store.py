"""MemoryAuthStore basic behaviors."""

from __future__ import annotations

import asyncio


from pywire_auth import MemoryAuthStore


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_create_and_get_user() -> None:
    store = MemoryAuthStore()
    user_id = _run(store.create_user(email="a@b.c", name="Alice"))
    record = _run(store.get_user(user_id))
    assert record is not None
    assert record["user_id"] == user_id
    assert record["email"] == "a@b.c"


def test_link_provider_and_find() -> None:
    store = MemoryAuthStore()
    user_id = _run(store.create_user(email="a@b.c"))
    _run(store.link_provider(user_id, "google", "sub123", {"email": "a@b.c"}))

    found = _run(store.find_by_provider("google", "sub123"))
    assert found is not None
    assert found["user_id"] == user_id
    assert "google" in found["linked"]


def test_find_missing_returns_none() -> None:
    store = MemoryAuthStore()
    assert _run(store.find_by_provider("google", "unknown")) is None


def test_password_hash_roundtrip() -> None:
    store = MemoryAuthStore()
    user_id = _run(store.create_user(email="a@b.c"))
    _run(store.set_password_hash(user_id, "$argon2id$hash..."))
    assert _run(store.get_password_hash(user_id)) == "$argon2id$hash..."


def test_update_user_noop_if_missing() -> None:
    store = MemoryAuthStore()
    _run(store.update_user("nope", name="X"))  # should not raise
    assert _run(store.get_user("nope")) is None


def test_create_user_accepts_explicit_id() -> None:
    store = MemoryAuthStore()
    user_id = _run(store.create_user(user_id="custom-id", email="a@b"))
    assert user_id == "custom-id"
    record = _run(store.get_user("custom-id"))
    assert record is not None
    assert record["email"] == "a@b"
