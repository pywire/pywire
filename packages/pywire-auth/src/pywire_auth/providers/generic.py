"""Generic OIDC provider — any IdP exposing a discovery document.

Drop in for Auth0, Keycloak, Okta, Azure B2C, AWS Cognito, etc. Pass the
discovery URL (``/.well-known/openid-configuration``) and the provider
fetches endpoints + JWKS on first use.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from pywire.auth import Claim

from pywire_auth.providers.base import BaseOIDCProvider

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class GenericOIDCProvider(BaseOIDCProvider):
    name: str = "oidc"
    discovery_url: str = ""
    scopes: List[str] = field(default_factory=lambda: ["openid", "email", "profile"])
    claim_types: List[str] = field(
        default_factory=lambda: [
            "sub",
            "email",
            "email_verified",
            "name",
            "picture",
            "preferred_username",
        ]
    )
    # Set by _discover() on first use
    authorize_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    jwks_uri: str = ""
    issuer: str = ""

    _discovered: bool = field(default=False, init=False, repr=False)
    _discover_lock: Optional[asyncio.Lock] = field(default=None, init=False, repr=False)

    async def _ensure_discovered(self) -> None:
        if self._discovered:
            return
        if self._discover_lock is None:
            self._discover_lock = asyncio.Lock()
        async with self._discover_lock:
            if self._discovered:
                return
            if not self.discovery_url:
                if not all(
                    [self.authorize_endpoint, self.token_endpoint, self.jwks_uri]
                ):
                    raise RuntimeError(
                        "GenericOIDCProvider requires either discovery_url or "
                        "authorize_endpoint+token_endpoint+jwks_uri"
                    )
                self._discovered = True
                return
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self.discovery_url)
                resp.raise_for_status()
                doc = resp.json()
            self.authorize_endpoint = doc["authorization_endpoint"]
            self.token_endpoint = doc["token_endpoint"]
            self.userinfo_endpoint = doc.get("userinfo_endpoint", "")
            self.jwks_uri = doc["jwks_uri"]
            self.issuer = doc["issuer"]
            self._discovered = True

    async def authorize_url(self, *, redirect_uri: str, state: str, nonce: str) -> str:
        await self._ensure_discovered()
        return await super().authorize_url(
            redirect_uri=redirect_uri, state=state, nonce=nonce
        )

    async def exchange_code(
        self, *, code: str, redirect_uri: str, state: str, nonce: str
    ):
        await self._ensure_discovered()
        return await super().exchange_code(
            code=code, redirect_uri=redirect_uri, state=state, nonce=nonce
        )

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims: List[Claim] = []
        for claim_type in self.claim_types:
            if claim_type not in raw or raw[claim_type] is None:
                continue
            claims.append(Claim(type=claim_type, value=str(raw[claim_type])))
        return claims
