"""Base provider classes.

Two abstract bases:

- ``BaseOAuth2Provider`` — plain OAuth2 (no id_token / OIDC). Used by
  GitHub and anywhere only an access token + userinfo endpoint exist.

- ``BaseOIDCProvider`` — OIDC discovery doc + id_token validation. Used
  by Google, Microsoft, Auth0, the generic provider, and the local IdP.
"""

from __future__ import annotations

import logging
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
from authlib.jose import jwt

from pywire.auth import Claim, ClaimsPrincipal

logger = logging.getLogger(__name__)


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

    async def authorize_url(self, *, redirect_uri: str, state: str, nonce: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
        }
        query = urllib.parse.urlencode(params)
        return f"{self.authorize_endpoint}?{query}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str, state: str, nonce: str
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

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
    directly. The id_token ``iss``/``aud``/``exp``/``nonce`` are checked.
    """

    issuer: str = ""
    jwks_uri: str = ""

    # Populated lazily
    _jwks_cache: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)

    async def exchange_code(
        self, *, code: str, redirect_uri: str, state: str, nonce: str
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            id_token = token_data.get("id_token")
            if id_token:
                claims_dict = await self._verify_id_token(
                    id_token, nonce=nonce, client=client
                )
                raw = dict(claims_dict)
                # Some providers omit userinfo; skip call when id_token is
                # sufficient and `email`/`name` already present.
                if "email" not in raw or "name" not in raw:
                    access_token = token_data.get("access_token")
                    if access_token:
                        ui = await client.get(
                            self.userinfo_endpoint,
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        if ui.status_code < 400:
                            raw.update(ui.json())
            else:
                access_token = token_data["access_token"]
                ui = await client.get(
                    self.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                ui.raise_for_status()
                raw = ui.json()

        return self._build_principal(raw), token_data

    async def _verify_id_token(
        self, id_token: str, *, nonce: str, client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        jwks = await self._get_jwks(client)
        claims = jwt.decode(id_token, jwks)
        claims.validate()

        if self.issuer and claims.get("iss") != self.issuer:
            raise ValueError(
                f"id_token issuer mismatch: {claims.get('iss')!r} != {self.issuer!r}"
            )
        if self.client_id and claims.get("aud") not in (
            self.client_id,
            [self.client_id],
        ):
            aud = claims.get("aud")
            if not (isinstance(aud, list) and self.client_id in aud):
                raise ValueError("id_token audience mismatch")
        if nonce and claims.get("nonce") != nonce:
            raise ValueError("id_token nonce mismatch")

        return dict(claims)

    async def _get_jwks(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        if self._jwks_cache is not None:
            return self._jwks_cache
        if not self.jwks_uri:
            raise RuntimeError(f"Provider {self.name!r} has no jwks_uri configured")
        resp = await client.get(self.jwks_uri)
        resp.raise_for_status()
        self._jwks_cache = resp.json()
        return self._jwks_cache
