"""Microsoft / Azure AD OIDC provider.

Uses the v2.0 endpoint. For multi-tenant apps leave ``tenant`` as
``"common"``; for single-tenant set to the tenant GUID or friendly name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from pywire.auth import Claim

from pywire_auth.providers.base import BaseOIDCProvider


@dataclass(kw_only=True)
class MicrosoftProvider(BaseOIDCProvider):
    name: str = "microsoft"
    tenant: str = "common"
    scopes: List[str] = field(
        default_factory=lambda: ["openid", "email", "profile", "User.Read"]
    )
    authorize_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = "https://graph.microsoft.com/oidc/userinfo"
    jwks_uri: str = ""
    issuer: str = ""

    def __post_init__(self) -> None:
        base = f"https://login.microsoftonline.com/{self.tenant}"
        if not self.authorize_endpoint:
            self.authorize_endpoint = f"{base}/oauth2/v2.0/authorize"
        if not self.token_endpoint:
            self.token_endpoint = f"{base}/oauth2/v2.0/token"
        if not self.jwks_uri:
            self.jwks_uri = f"{base}/discovery/v2.0/keys"
        if not self.issuer:
            self.issuer = f"https://login.microsoftonline.com/{self.tenant}/v2.0"

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims: List[Claim] = []
        for key in ("sub", "email", "name", "preferred_username", "tid", "oid"):
            if key in raw and raw[key] is not None:
                claims.append(Claim(type=key, value=str(raw[key])))
        return claims
