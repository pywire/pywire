"""Base provider classes.

Two abstract bases:

- ``BaseOAuth2Provider`` — plain OAuth2 (no id_token / OIDC). Used by
  GitHub and anywhere only an access token + userinfo endpoint exist.

- ``BaseOIDCProvider`` — OIDC discovery doc + id_token validation. Used
  by Google, Microsoft, Auth0, the generic provider, and the local IdP.

Both use PKCE (S256): the login route makes a ``code_verifier``, sends its
challenge with the authorize request and the verifier with the code
exchange, so a stolen authorization code is useless on its own.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError

from pywire.auth import Claim, ClaimsPrincipal

logger = logging.getLogger(__name__)

# Signature algorithms accepted on id_tokens. Asymmetric only: the keys come
# from the provider's JWKS, and a token must not be able to choose HMAC.
ID_TOKEN_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
]
# Least time between two JWKS fetches caused by an unknown key id, so tokens
# naming made-up keys can't turn the app into a JWKS request pump.
_JWKS_REFETCH_INTERVAL = 60.0


@dataclass(kw_only=True)
class BaseOAuth2Provider(ABC):
    """OAuth2 authorization code flow, no id_token."""

    name: str
    client_id: str
    client_secret: str
    authorize_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    scopes: List[str] = field(default_factory=list)

    async def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        # OIDC providers bind the nonce into the returned id_token; without
        # sending it here the id_token's `nonce` claim is absent and
        # ``_verify_id_token`` raises "id_token nonce mismatch". Plain
        # OAuth2 providers (GitHub, Facebook) ignore the extra param.
        if nonce:
            params["nonce"] = nonce
        query = urllib.parse.urlencode(params)
        return f"{self.authorize_endpoint}?{query}"

    async def _exchange(
        self,
        client: httpx.AsyncClient,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> Dict[str, Any]:
        token_resp = await client.post(
            self.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        return token_resp.json()

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_data = await self._exchange(
                client,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            access_token = token_data["access_token"]
            userinfo_resp = await client.get(
                self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            raw = userinfo_resp.json()

        principal = self._build_principal(raw)
        return principal, token_data

    async def refresh(
        self, refresh_token: str
    ) -> Optional[Tuple[ClaimsPrincipal, Dict[str, Any]]]:
        if not refresh_token:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code >= 400:
                return None
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return None
            userinfo_resp = await client.get(
                self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code >= 400:
                return None
            raw = userinfo_resp.json()
        return self._build_principal(raw), token_data

    @abstractmethod
    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        """Translate provider-specific raw userinfo into Claim objects."""

    def _build_principal(self, raw: Dict[str, Any]) -> ClaimsPrincipal:
        subject = str(raw.get("sub") or raw.get("id") or "")
        claims = self.map_claims(raw)
        name = str(raw.get("name") or raw.get("login") or "")
        return ClaimsPrincipal(
            is_authenticated=True,
            name=name,
            user_id=f"{self.name}:{subject}" if subject else "",
            claims=claims,
            raw=raw,
        )


@dataclass(kw_only=True)
class BaseOIDCProvider(BaseOAuth2Provider, ABC):
    """OAuth2 + OIDC id_token validation.

    Subclasses supply a ``discovery_url`` or override the endpoints
    directly. Sign-in requires an id_token signed by a key in the
    provider's JWKS, with the expected ``iss`` and ``aud``, an ``exp`` in
    the future and the ``nonce`` this login sent. Userinfo only adds to it,
    and only when it describes the same ``sub``.
    """

    issuer: str = ""
    jwks_uri: str = ""

    # Populated lazily
    _jwks_cache: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)
    _jwks_fetched_at: float = field(default=0.0, init=False, repr=False)

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_data = await self._exchange(
                client,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            id_token = token_data.get("id_token")
            if not id_token:
                raise ValueError("token response has no id_token")
            raw = await self._verify_id_token(id_token, nonce=nonce, client=client)
            # Some providers leave profile claims out of the id_token.
            if "email" not in raw or "name" not in raw:
                access_token = token_data.get("access_token")
                if access_token and self.userinfo_endpoint:
                    ui = await client.get(
                        self.userinfo_endpoint,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if ui.status_code < 400:
                        info = ui.json()
                        if str(info.get("sub")) != str(raw["sub"]):
                            raise ValueError("userinfo sub differs from id_token sub")
                        raw = {**info, **raw}

        return self._build_principal(raw), token_data

    async def _verify_id_token(
        self, id_token: str, *, nonce: str, client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        if not nonce:
            raise ValueError("id_token check needs the login's nonce")
        options: Dict[str, Any] = {
            "sub": {"essential": True},
            "exp": {"essential": True},
            "nonce": {"essential": True, "value": nonce},
        }
        if self.issuer:
            options["iss"] = {"essential": True, "value": self.issuer}
        if self.client_id:
            options["aud"] = {"essential": True, "value": self.client_id}
        claims = await self._decode_id_token(id_token, client, options)
        claims.validate()
        return dict(claims)

    async def _decode_id_token(
        self, id_token: str, client: httpx.AsyncClient, options: Dict[str, Any]
    ) -> Any:
        jwt = JsonWebToken(ID_TOKEN_ALGORITHMS)
        try:
            keys = JsonWebKey.import_key_set(await self._get_jwks(client))
            return jwt.decode(id_token, keys, claims_options=options)
        except (JoseError, ValueError):
            # Providers rotate keys: a token signed with a key we haven't
            # seen gets one fresh look at the JWKS (rate-limited).
            if time.monotonic() - self._jwks_fetched_at < _JWKS_REFETCH_INTERVAL:
                raise
            keys = JsonWebKey.import_key_set(await self._get_jwks(client, refresh=True))
            return jwt.decode(id_token, keys, claims_options=options)

    async def _get_jwks(
        self, client: httpx.AsyncClient, *, refresh: bool = False
    ) -> Dict[str, Any]:
        if self._jwks_cache is not None and not refresh:
            return self._jwks_cache
        if not self.jwks_uri:
            raise RuntimeError(f"Provider {self.name!r} has no jwks_uri configured")
        resp = await client.get(self.jwks_uri)
        resp.raise_for_status()
        self._jwks_cache = resp.json()
        self._jwks_fetched_at = time.monotonic()
        return self._jwks_cache
