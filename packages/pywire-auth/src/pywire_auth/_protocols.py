"""Structural interfaces for auth providers and stores."""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

from pywire.auth import Claim, ClaimsPrincipal


@runtime_checkable
class AuthStore(Protocol):
    """Persistent user + identity store.

    Used by the local IdP and by account-linking flows. Apps using only
    external OIDC providers don't need a store.
    """

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]: ...

    async def find_by_provider(
        self, provider: str, subject: str
    ) -> Optional[Dict[str, Any]]: ...

    async def create_user(self, **fields: Any) -> str: ...

    async def update_user(self, user_id: str, **fields: Any) -> None: ...

    async def link_provider(
        self,
        user_id: str,
        provider: str,
        subject: str,
        claims: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    async def get_password_hash(self, user_id: str) -> Optional[str]: ...

    async def set_password_hash(self, user_id: str, hash: str) -> None: ...


class OIDCProvider(Protocol):
    """Structural shape for OAuth2/OIDC login providers."""

    name: str
    scopes: List[str]

    async def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str
    ) -> str: ...

    async def exchange_code(
        self, *, code: str, redirect_uri: str, state: str, nonce: str
    ) -> Tuple[ClaimsPrincipal, Dict[str, Any]]: ...

    async def refresh(
        self, refresh_token: str
    ) -> Optional[Tuple[ClaimsPrincipal, Dict[str, Any]]]: ...

    def map_claims(self, raw: Dict[str, Any]) -> List[Claim]: ...
