"""GitHub OAuth2 provider (not OIDC — no id_token)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from pywire.auth import Claim

from pywire_auth.providers.base import BaseOAuth2Provider


@dataclass(kw_only=True)
class GitHubProvider(BaseOAuth2Provider):
    name: str = "github"
    authorize_endpoint: str = "https://github.com/login/oauth/authorize"
    token_endpoint: str = "https://github.com/login/oauth/access_token"
    userinfo_endpoint: str = "https://api.github.com/user"
    scopes: List[str] = field(default_factory=lambda: ["read:user", "user:email"])

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims: List[Claim] = []
        if "id" in raw:
            claims.append(Claim(type="sub", value=str(raw["id"])))
        if "login" in raw:
            claims.append(Claim(type="login", value=str(raw["login"])))
        if "email" in raw and raw["email"]:
            claims.append(Claim(type="email", value=str(raw["email"])))
        if "name" in raw and raw["name"]:
            claims.append(Claim(type="name", value=str(raw["name"])))
        if "avatar_url" in raw:
            claims.append(Claim(type="picture", value=str(raw["avatar_url"])))
        return claims
