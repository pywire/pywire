"""OAuth2 / OIDC providers."""

from pywire_auth.providers.base import BaseOIDCProvider, BaseOAuth2Provider
from pywire_auth.providers.generic import GenericOIDCProvider
from pywire_auth.providers.github import GitHubProvider
from pywire_auth.providers.google import GoogleProvider

__all__ = [
    "BaseOAuth2Provider",
    "BaseOIDCProvider",
    "GenericOIDCProvider",
    "GitHubProvider",
    "GoogleProvider",
]
