"""Local IdP tests — registration, login, id_token round-trip."""

from __future__ import annotations

import asyncio

import pytest

from pywire_auth import LocalIdP, MemoryAuthStore, TokenIssuer


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_idp() -> LocalIdP:
    return LocalIdP(
        store=MemoryAuthStore(),
        secret="x" * 64,
        issuer="test-issuer",
        audience="test-app",
    )


def test_requires_secret_or_token_issuer() -> None:
    with pytest.raises(ValueError):
        LocalIdP(store=MemoryAuthStore())


def test_create_and_verify_credentials() -> None:
    idp = _make_idp()
    user_id = _run(
        idp.create_user(email="alice@example.com", password="hunter2", name="Alice")
    )
    principal = _run(
        idp.verify_credentials(email="alice@example.com", password="hunter2")
    )
    assert principal is not None
    assert principal.is_authenticated
    assert principal.user_id == f"local:{user_id}"
    assert principal.name == "Alice"
    assert principal.has_claim("email", "alice@example.com")


def test_wrong_password_returns_none() -> None:
    idp = _make_idp()
    _run(idp.create_user(email="alice@example.com", password="hunter2"))
    assert (
        _run(idp.verify_credentials(email="alice@example.com", password="WRONG"))
        is None
    )


def test_unknown_email_returns_none() -> None:
    idp = _make_idp()
    assert (
        _run(idp.verify_credentials(email="nobody@example.com", password="x")) is None
    )


def test_unknown_email_costs_a_password_check() -> None:
    """A missing user takes as long as a wrong password (no enumeration)."""
    idp = _make_idp()
    calls = []
    real_verify = idp._verify

    async def verify(pw_hash: str, password: str) -> bool:
        calls.append(pw_hash)
        return await real_verify(pw_hash, password)

    idp._verify = verify  # type: ignore[method-assign]
    _run(idp.verify_credentials(email="nobody@example.com", password="x"))
    assert len(calls) == 1


def test_legacy_mixed_case_account_still_signs_in() -> None:
    idp = _make_idp()
    uid = _run(idp.create_user(email="old@example.com", password="pw"))
    # An account linked before emails were normalized.
    _run(idp.store.link_provider(uid, "local", "Old@Example.com"))
    assert _run(idp.verify_credentials(email="Old@Example.com", password="pw"))


def test_duplicate_email_rejected() -> None:
    idp = _make_idp()
    _run(idp.create_user(email="alice@example.com", password="hunter2"))
    with pytest.raises(ValueError):
        _run(idp.create_user(email="alice@example.com", password="again"))


def test_change_password_happy_path() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="old"))
    ok = _run(
        idp.change_password(user_id=user_id, old_password="old", new_password="new")
    )
    assert ok is True
    assert _run(idp.verify_credentials(email="a@b.c", password="old")) is None
    assert _run(idp.verify_credentials(email="a@b.c", password="new")) is not None


def test_change_password_wrong_old_rejected() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="old"))
    ok = _run(
        idp.change_password(user_id=user_id, old_password="WRONG", new_password="new")
    )
    assert ok is False


def test_reset_password_skips_old() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="old"))
    _run(idp.reset_password(user_id=user_id, new_password="reset"))
    assert _run(idp.verify_credentials(email="a@b.c", password="reset")) is not None


def test_id_token_roundtrip() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="hunter2"))

    token = idp.issue_id_token(user_id=user_id, claims={"role": "admin"})
    payload = idp.verify_id_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["iss"] == "test-issuer"
    assert payload["aud"] == "test-app"
    assert payload["role"] == "admin"


def test_id_token_tampered_rejected() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="hunter2"))
    token = idp.issue_id_token(user_id=user_id)
    # Corrupt the signature segment
    tampered = token[:-4] + "XXXX"
    assert idp.verify_id_token(tampered) is None


def test_principal_from_id_token() -> None:
    idp = _make_idp()
    user_id = _run(idp.create_user(email="a@b.c", password="hunter2", name="A"))
    token = idp.issue_id_token(user_id=user_id)
    principal = _run(idp.principal_from_id_token(token))
    assert principal is not None
    assert principal.user_id == f"local:{user_id}"
    assert principal.has_claim("email", "a@b.c")


def test_hs256_public_jwks_raises() -> None:
    issuer = TokenIssuer(issuer="x", algorithm="HS256", secret="x" * 32)
    with pytest.raises(RuntimeError):
        issuer.public_jwks()


def test_unsupported_algorithm_rejected() -> None:
    with pytest.raises(ValueError):
        TokenIssuer(algorithm="ES256", secret="x" * 32)
