"""Auth0 OIDC provider.

Pass the tenant domain (e.g. ``"myapp.auth0.com"``) and endpoints are
derived from Auth0's well-known discovery URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from pywire.auth import Claim

from pywire_auth.providers.generic import GenericOIDCProvider


@dataclass(kw_only=True)
class Auth0Provider(GenericOIDCProvider):
    name: str = "auth0"
    domain: str = ""

    def __post_init__(self) -> None:
        if not self.domain and not self.discovery_url:
            raise ValueError(
                "Auth0Provider requires either domain='your-tenant.auth0.com' "
                "or an explicit discovery_url"
            )
        if self.domain and not self.discovery_url:
            self.discovery_url = (
                f"https://{self.domain}/.well-known/openid-configuration"
            )

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]:
        claims = super().map_claims(raw)
        for role_key in ("https://auth0.com/roles", "roles"):
            roles = raw.get(role_key)
            if isinstance(roles, list):
                for role in roles:
                    claims.append(Claim(type="role", value=str(role)))
        return claims
