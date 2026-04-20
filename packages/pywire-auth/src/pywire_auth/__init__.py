"""pywire-auth — OAuth2 / OIDC providers and identity store adapters.

Public API:

- :func:`connect_auth` — single integration entry point
- :class:`AuthActions` — one-call claim/session mutations (`app.state.auth`)
- :class:`AuthMiddleware` — ASGI middleware that populates scope['user']
- :class:`LocalIdP` + :class:`TokenIssuer` — database-backed local provider
- OIDC providers: :class:`GoogleProvider`, :class:`GitHubProvider`,
  :class:`MicrosoftProvider`, :class:`FacebookProvider`,
  :class:`Auth0Provider`, :class:`GenericOIDCProvider`
- Store adapters: :class:`MemoryAuthStore`, :class:`SQLAlchemyAuthStore`
  (requires ``pip install pywire-auth[sqlalchemy]``)
- Structural interfaces: :class:`AuthStore`, :class:`OIDCProvider`,
  :class:`BaseOAuth2Provider`, :class:`BaseOIDCProvider`
"""

from pywire_auth._protocols import AuthStore, OIDCProvider
from pywire_auth.actions import AuthActions
from pywire_auth.integration import connect_auth
from pywire_auth.middleware import AuthMiddleware
from pywire_auth.local import LocalIdP, TokenIssuer
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

try:
    from pywire_auth.stores.sqlalchemy import SQLAlchemyAuthStore
except ImportError:
    SQLAlchemyAuthStore = None  # type: ignore[assignment,misc]

__all__ = [
    "Auth0Provider",
    "AuthActions",
    "AuthMiddleware",
    "AuthStore",
    "BaseOAuth2Provider",
    "BaseOIDCProvider",
    "FacebookProvider",
    "GenericOIDCProvider",
    "GitHubProvider",
    "GoogleProvider",
    "LocalIdP",
    "MemoryAuthStore",
    "MicrosoftProvider",
    "SQLAlchemyAuthStore",
    "OIDCProvider",
    "TokenIssuer",
    "connect_auth",
]
