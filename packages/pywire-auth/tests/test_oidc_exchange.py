"""OIDC code exchange: PKCE, id_token checks, userinfo binding, key rotation."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, JsonWebToken

from pywire_auth import GoogleProvider, TokenIssuer
from pywire_auth.providers import base as base_mod

ISSUER = "https://accounts.google.com"
CLIENT = "cid"
NONCE = "n0nce"


def _key(kid: str) -> Any:
    return JsonWebKey.generate_key("RSA", 2048, options={"kid": kid}, is_private=True)


def _jwks(*keys: Any) -> Dict[str, Any]:
    return {"keys": [k.as_dict(is_private=False) for k in keys]}


def _id_token(key: Any, **overrides: Any) -> str:
    now = int(time.time())
    payload: Dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT,
        "sub": "u1",
        "iat": now,
        "exp": now + 300,
        "nonce": NONCE,
        "email": "a@b.c",
        "name": "A",
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    token = JsonWebToken(["RS256"]).encode(
        {"alg": "RS256", "kid": key.kid}, payload, key
    )
    return token.decode()


class _IdP:
    """Answers the token, userinfo and JWKS endpoints."""

    def __init__(self, token_data: Dict[str, Any], jwks: Dict[str, Any]) -> None:
        self.token_data = token_data
        self.jwks = jwks
        self.userinfo: Dict[str, Any] = {"sub": "u1", "email": "a@b.c", "name": "A"}
        self.token_forms: List[Dict[str, List[str]]] = []
        self.jwks_hits = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/token"):
            self.token_forms.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json=self.token_data)
        if path.endswith("/certs"):
            self.jwks_hits += 1
            return httpx.Response(200, json=self.jwks)
        if path.endswith("/userinfo"):
            return httpx.Response(200, json=self.userinfo)
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _IdP]:
    def make(token_data: Dict[str, Any], jwks: Dict[str, Any]) -> _IdP:
        fake = _IdP(token_data, jwks)
        real = httpx.AsyncClient

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return real(transport=httpx.MockTransport(fake.handler))

        monkeypatch.setattr(base_mod.httpx, "AsyncClient", client)
        return fake

    return make


def _provider() -> GoogleProvider:
    return GoogleProvider(
        client_id=CLIENT,
        client_secret="sec",
        token_endpoint="https://idp.test/token",
        userinfo_endpoint="https://idp.test/userinfo",
        jwks_uri="https://idp.test/certs",
    )


async def _exchange(provider: GoogleProvider, nonce: str = NONCE) -> Any:
    return await provider.exchange_code(
        code="c",
        redirect_uri="https://app/cb",
        state="s",
        nonce=nonce,
        code_verifier="v" * 50,
    )


@pytest.mark.asyncio
async def test_authorize_url_sends_pkce_challenge() -> None:
    url = await _provider().authorize_url(
        redirect_uri="https://app/cb", state="s", nonce="n", code_challenge="ch"
    )
    qs = parse_qs(urlsplit(url).query)
    assert qs["code_challenge"] == ["ch"]
    assert qs["code_challenge_method"] == ["S256"]


@pytest.mark.asyncio
async def test_valid_id_token_signs_in_and_sends_verifier(idp) -> None:
    key = _key("k1")
    fake = idp({"access_token": "at", "id_token": _id_token(key)}, _jwks(key))
    principal, _ = await _exchange(_provider())
    assert principal.user_id == "google:u1"
    assert fake.token_forms[0]["code_verifier"] == ["v" * 50]


@pytest.mark.asyncio
async def test_missing_id_token_is_refused(idp) -> None:
    key = _key("k1")
    idp({"access_token": "at"}, _jwks(key))
    with pytest.raises(ValueError):
        await _exchange(_provider())


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": None},
        {"nonce": "other"},
        {"exp": None},
        {"exp": int(time.time()) - 600},
        {"iss": "https://evil.example"},
        {"aud": "someone-else"},
    ],
)
@pytest.mark.asyncio
async def test_bad_id_tokens_are_refused(idp, overrides) -> None:
    key = _key("k1")
    idp({"access_token": "at", "id_token": _id_token(key, **overrides)}, _jwks(key))
    with pytest.raises(Exception):
        await _exchange(_provider())


@pytest.mark.asyncio
async def test_empty_nonce_is_refused(idp) -> None:
    key = _key("k1")
    idp({"access_token": "at", "id_token": _id_token(key, nonce="")}, _jwks(key))
    with pytest.raises(ValueError):
        await _exchange(_provider(), nonce="")


@pytest.mark.asyncio
async def test_hmac_signed_id_token_is_refused(idp) -> None:
    key = _key("k1")
    now = int(time.time())
    forged = JsonWebToken(["HS256"]).encode(
        {"alg": "HS256", "kid": "k1"},
        {"iss": ISSUER, "aud": CLIENT, "sub": "u1", "exp": now + 60, "nonce": NONCE},
        "secret",
    )
    idp({"access_token": "at", "id_token": forged.decode()}, _jwks(key))
    with pytest.raises(Exception):
        await _exchange(_provider())


@pytest.mark.asyncio
async def test_userinfo_for_another_subject_is_refused(idp) -> None:
    key = _key("k1")
    fake = idp(
        {"access_token": "at", "id_token": _id_token(key, email=None, name=None)},
        _jwks(key),
    )
    fake.userinfo = {"sub": "someone-else", "email": "x@y.z", "name": "X"}
    with pytest.raises(ValueError):
        await _exchange(_provider())


@pytest.mark.asyncio
async def test_rotated_signing_key_refetches_jwks(idp) -> None:
    old, new = _key("old"), _key("new")
    fake = idp({"access_token": "at", "id_token": _id_token(old)}, _jwks(old))
    provider = _provider()
    await _exchange(provider)
    # The IdP rotates keys; the cached JWKS lacks the new kid.
    fake.jwks = _jwks(new)
    fake.token_data = {"access_token": "at", "id_token": _id_token(new)}
    provider._jwks_fetched_at -= 3600
    principal, _ = await _exchange(provider)
    assert principal.user_id == "google:u1"
    assert fake.jwks_hits == 2
    # Unknown kids don't trigger a fetch per request.
    fake.token_data = {"access_token": "at", "id_token": _id_token(_key("made-up"))}
    with pytest.raises(Exception):
        await _exchange(provider)
    assert fake.jwks_hits == 2


def test_token_issuer_claims_cannot_override_registered_claims() -> None:
    issuer = TokenIssuer(secret="s" * 32)
    token = issuer.issue(
        subject="u1",
        audience="app",
        ttl=60,
        claims={"iss": "evil", "aud": "other", "exp": 9999999999, "sub": "root"},
    )
    decoded = issuer.verify(token, audience="app")
    assert decoded is not None
    assert decoded["sub"] == "u1" and decoded["aud"] == "app"
    assert decoded["iss"] == issuer.issuer
    assert decoded["exp"] <= time.time() + 61


def test_token_issuer_requires_exp() -> None:
    issuer = TokenIssuer(secret="s" * 32)
    token = JsonWebToken(["HS256"]).encode(
        {"alg": "HS256"}, {"iss": issuer.issuer, "sub": "u1", "aud": "app"}, "s" * 32
    )
    assert issuer.verify(token.decode(), audience="app") is None
