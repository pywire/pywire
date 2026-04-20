"""Facebook OAuth2 provider (not OIDC)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from pywire.auth import Claim

from pywire_auth.providers.base import BaseOAuth2Provider


@dataclass(kw_only=True)
class FacebookProvider(BaseOAuth2Provider):
    name: str = "facebook"
    authorize_endpoint: str = "https://www.facebook.com/v18.0/dialog/oauth"
    token_endpoint: str = "https://graph.facebook.com/v18.0/oauth/access_token"
    userinfo_endpoint: str = (
        "https://graph.facebook.com/me?fields=id,name,email,picture"
    )
    scopes: List[str] = field(default_factory=lambda: ["email", "public_profile"])

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims: List[Claim] = []
        if "id" in raw:
            claims.append(Claim(type="sub", value=str(raw["id"])))
        if "email" in raw and raw["email"]:
            claims.append(Claim(type="email", value=str(raw["email"])))
        if "name" in raw and raw["name"]:
            claims.append(Claim(type="name", value=str(raw["name"])))
        picture = raw.get("picture") or {}
        if isinstance(picture, dict):
            data = picture.get("data") or {}
            url = data.get("url")
            if url:
                claims.append(Claim(type="picture", value=str(url)))
        return claims
