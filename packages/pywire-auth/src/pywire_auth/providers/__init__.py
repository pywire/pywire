"""OAuth2 / OIDC providers."""

from pywire_auth.providers.auth0 import Auth0Provider
from pywire_auth.providers.base import BaseOIDCProvider, BaseOAuth2Provider
from pywire_auth.providers.facebook import FacebookProvider
from pywire_auth.providers.generic import GenericOIDCProvider
from pywire_auth.providers.github import GitHubProvider
from pywire_auth.providers.google import GoogleProvider
from pywire_auth.providers.microsoft import MicrosoftProvider

__all__ = [
    "Auth0Provider",
    "BaseOAuth2Provider",
    "BaseOIDCProvider",
    "FacebookProvider",
    "GenericOIDCProvider",
    "GitHubProvider",
    "GoogleProvider",
    "MicrosoftProvider",
]
