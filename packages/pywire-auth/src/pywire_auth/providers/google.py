"""Google OIDC provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from pywire.auth import Claim

from pywire_auth.providers.base import BaseOIDCProvider

# Google's discovery doc is stable and well-known.
GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUER = "https://accounts.google.com"


@dataclass(kw_only=True)
class GoogleProvider(BaseOIDCProvider):
    name: str = "google"
    authorize_endpoint: str = GOOGLE_AUTHORIZE
    token_endpoint: str = GOOGLE_TOKEN
    userinfo_endpoint: str = GOOGLE_USERINFO
    jwks_uri: str = GOOGLE_JWKS
    issuer: str = GOOGLE_ISSUER
    scopes: List[str] = field(default_factory=lambda: ["openid", "email", "profile"])

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims: List[Claim] = []
        if "sub" in raw:
            claims.append(Claim(type="sub", value=str(raw["sub"])))
        if "email" in raw:
            claims.append(Claim(type="email", value=str(raw["email"])))
            if raw.get("email_verified"):
                claims.append(Claim(type="email_verified", value="true"))
        if "name" in raw:
            claims.append(Claim(type="name", value=str(raw["name"])))
        if "picture" in raw:
            claims.append(Claim(type="picture", value=str(raw["picture"])))
        if "hd" in raw:  # hosted domain (Google Workspace)
            claims.append(Claim(type="hd", value=str(raw["hd"])))
        return claims
