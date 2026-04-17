"""Provider claim-mapping + instantiation tests.

Network-level exchange_code / refresh tests live elsewhere and use
httpx transport mocks.
"""

from __future__ import annotations

import pytest

from pywire_auth import GitHubProvider, GoogleProvider, GenericOIDCProvider


def test_google_defaults() -> None:
    p = GoogleProvider(client_id="cid", client_secret="sec")
    assert p.name == "google"
    assert p.issuer == "https://accounts.google.com"
    assert "openid" in p.scopes
    assert "email" in p.scopes


def test_google_claim_mapping() -> None:
    p = GoogleProvider(client_id="cid", client_secret="sec")
    raw = {
        "sub": "123",
        "email": "a@b.c",
        "email_verified": True,
        "name": "Alice",
        "picture": "https://example.com/a.png",
        "hd": "example.com",
    }
    claims = p.map_claims(raw)
    types = {c.type: c.value for c in claims}
    assert types["sub"] == "123"
    assert types["email"] == "a@b.c"
    assert types["email_verified"] == "true"
    assert types["name"] == "Alice"
    assert types["hd"] == "example.com"


def test_google_build_principal() -> None:
    p = GoogleProvider(client_id="cid", client_secret="sec")
    principal = p._build_principal({"sub": "42", "name": "A", "email": "a@b"})
    assert principal.is_authenticated
    assert principal.user_id == "google:42"
    assert principal.name == "A"
    assert principal.has_claim("email", "a@b")


def test_github_defaults_oauth2_only() -> None:
    p = GitHubProvider(client_id="cid", client_secret="sec")
    assert p.name == "github"
    assert "read:user" in p.scopes
    # GitHub is OAuth2, not OIDC
    assert not hasattr(p, "issuer") or not getattr(p, "issuer", "")


def test_github_claim_mapping() -> None:
    p = GitHubProvider(client_id="cid", client_secret="sec")
    raw = {
        "id": 42,
        "login": "alice",
        "email": "a@b.c",
        "name": "Alice",
        "avatar_url": "https://example.com/a.png",
    }
    claims = {c.type: c.value for c in p.map_claims(raw)}
    assert claims["sub"] == "42"
    assert claims["login"] == "alice"
    assert claims["picture"] == "https://example.com/a.png"


def test_github_build_principal_uses_id() -> None:
    p = GitHubProvider(client_id="cid", client_secret="sec")
    principal = p._build_principal({"id": 7, "login": "bob"})
    assert principal.user_id == "github:7"
    # Name falls back to login when name missing
    assert principal.name == "bob"


def test_generic_requires_discovery_or_endpoints() -> None:
    p = GenericOIDCProvider(client_id="cid", client_secret="sec")
    import asyncio

    with pytest.raises(RuntimeError):
        asyncio.new_event_loop().run_until_complete(p._ensure_discovered())


def test_generic_with_explicit_endpoints() -> None:
    p = GenericOIDCProvider(
        client_id="cid",
        client_secret="sec",
        authorize_endpoint="https://idp/authorize",
        token_endpoint="https://idp/token",
        userinfo_endpoint="https://idp/userinfo",
        jwks_uri="https://idp/jwks.json",
        issuer="https://idp",
    )
    import asyncio

    asyncio.new_event_loop().run_until_complete(p._ensure_discovered())
    assert p.authorize_endpoint == "https://idp/authorize"


def test_generic_claim_mapping() -> None:
    p = GenericOIDCProvider(
        client_id="cid",
        client_secret="sec",
        authorize_endpoint="https://idp/authorize",
        token_endpoint="https://idp/token",
        userinfo_endpoint="https://idp/userinfo",
        jwks_uri="https://idp/jwks.json",
    )
    claims = {
        c.type: c.value
        for c in p.map_claims(
            {"sub": "x", "email": "a@b.c", "name": "Alice", "ignored": "y"}
        )
    }
    assert claims == {"sub": "x", "email": "a@b.c", "name": "Alice"}
