"""Provider claim-mapping + instantiation tests.

Network-level exchange_code / refresh tests live elsewhere and use
httpx transport mocks.
"""

from __future__ import annotations

import pytest

from pywire_auth import (
    Auth0Provider,
    FacebookProvider,
    GenericOIDCProvider,
    GitHubProvider,
    GoogleProvider,
    MicrosoftProvider,
)


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


def test_microsoft_defaults_to_common_tenant() -> None:
    p = MicrosoftProvider(client_id="cid", client_secret="sec")
    assert p.name == "microsoft"
    assert p.tenant == "common"
    assert p.issuer.endswith("/common/v2.0")
    assert "login.microsoftonline.com/common" in p.authorize_endpoint


def test_microsoft_single_tenant() -> None:
    p = MicrosoftProvider(
        client_id="cid", client_secret="sec", tenant="myorg.onmicrosoft.com"
    )
    assert "myorg.onmicrosoft.com" in p.issuer
    assert "myorg.onmicrosoft.com" in p.token_endpoint


def test_microsoft_claim_mapping() -> None:
    p = MicrosoftProvider(client_id="cid", client_secret="sec")
    claims = {
        c.type: c.value
        for c in p.map_claims(
            {"sub": "s", "email": "a@b", "tid": "tenant-id", "oid": "obj-id"}
        )
    }
    assert claims == {
        "sub": "s",
        "email": "a@b",
        "tid": "tenant-id",
        "oid": "obj-id",
    }


def test_facebook_claim_mapping_nested_picture() -> None:
    p = FacebookProvider(client_id="cid", client_secret="sec")
    raw = {
        "id": "42",
        "name": "Alice",
        "email": "a@b.c",
        "picture": {"data": {"url": "https://fb/a.png", "width": 200}},
    }
    claims = {c.type: c.value for c in p.map_claims(raw)}
    assert claims["sub"] == "42"
    assert claims["picture"] == "https://fb/a.png"


def test_auth0_derives_discovery_from_domain() -> None:
    p = Auth0Provider(
        client_id="cid", client_secret="sec", domain="myapp.auth0.com"
    )
    assert p.discovery_url == (
        "https://myapp.auth0.com/.well-known/openid-configuration"
    )


def test_auth0_requires_domain_or_discovery_url() -> None:
    with pytest.raises(ValueError):
        Auth0Provider(client_id="cid", client_secret="sec")


def test_auth0_maps_roles_claim() -> None:
    p = Auth0Provider(
        client_id="cid", client_secret="sec", domain="myapp.auth0.com"
    )
    raw = {"sub": "x", "roles": ["admin", "editor"]}
    claims = [(c.type, c.value) for c in p.map_claims(raw)]
    assert ("sub", "x") in claims
    assert ("role", "admin") in claims
    assert ("role", "editor") in claims


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
