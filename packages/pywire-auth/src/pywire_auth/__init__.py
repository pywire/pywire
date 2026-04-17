"""pywire-auth — OAuth2 / OIDC providers and identity store adapters.

Public API:

- :func:`connect_auth` — single integration entry point
- :class:`AuthMiddleware` — ASGI middleware that populates scope['user']
- Providers: :class:`GoogleProvider`, :class:`GitHubProvider`,
  :class:`GenericOIDCProvider`
- Store adapters: :class:`MemoryAuthStore`
- Structural interfaces: :class:`AuthStore`, :class:`OIDCProvider`
"""

from pywire_auth._protocols import AuthStore, OIDCProvider
from pywire_auth.integration import connect_auth
from pywire_auth.middleware import AuthMiddleware
from pywire_auth.providers import (
    Auth0Provider,
    BaseOAuth2Provider,
    BaseOIDCProvider,
    FacebookProvider,
    GenericOIDCProvider,
    GitHubProvider,
    GoogleProvider,
    MicrosoftProvider,
)
from pywire_auth.stores import MemoryAuthStore

__all__ = [
    "Auth0Provider",
    "AuthMiddleware",
    "AuthStore",
    "BaseOAuth2Provider",
    "BaseOIDCProvider",
    "FacebookProvider",
    "GenericOIDCProvider",
    "GitHubProvider",
    "GoogleProvider",
    "MemoryAuthStore",
    "MicrosoftProvider",
    "OIDCProvider",
    "connect_auth",
]
