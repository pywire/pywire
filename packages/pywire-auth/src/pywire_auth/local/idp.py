"""LocalIdP — DB-backed identity provider with Argon2 password hashing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from pywire.auth import Claim, ClaimsPrincipal

from pywire_auth._protocols import AuthStore
from pywire_auth.local.token import TokenIssuer

logger = logging.getLogger(__name__)


@dataclass
class LocalIdP:
    """DB-backed identity provider with OIDC-native token issuance.

    - Registration: :meth:`create_user`
    - Login (password): :meth:`verify_credentials` → ``ClaimsPrincipal``
    - Machine tokens: :meth:`issue_id_token` → signed JWT

    The ``audience`` defaults to the issuer for single-app deployments;
    override per :meth:`issue_id_token` for multi-audience setups.
    """

    store: AuthStore
    # Supply one of: secret (HS256), OR configure a TokenIssuer explicitly
    secret: str = ""
    issuer: str = "pywire-auth-local"
    audience: str = ""
    token_issuer: Optional[TokenIssuer] = None
    _hasher: PasswordHasher = field(default_factory=PasswordHasher, repr=False)

    def __post_init__(self) -> None:
        if self.token_issuer is None:
            if not self.secret:
                raise ValueError(
                    "LocalIdP requires either secret=... (HS256) or an "
                    "explicit token_issuer=TokenIssuer(...)"
                )
            self.token_issuer = TokenIssuer(
                issuer=self.issuer, algorithm="HS256", secret=self.secret
            )
        else:
            # Ensure the issuer string matches any external token_issuer.
            self.issuer = self.token_issuer.issuer
        if not self.audience:
            self.audience = self.issuer

    # --- Registration + credential flows ---

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        claims: Optional[Dict[str, Any]] = None,
        name: str = "",
        **extra: Any,
    ) -> str:
        existing = await self.store.find_by_provider("local", email)
        if existing is not None:
            raise ValueError(f"User with email {email!r} already exists")

        user_id = await self.store.create_user(
            email=email, name=name, claims=claims or {}, **extra
        )
        pw_hash = self._hasher.hash(password)
        await self.store.set_password_hash(user_id, pw_hash)
        await self.store.link_provider(
            user_id, "local", email, claims=claims or {"email": email}
        )
        return user_id

    async def verify_credentials(
        self, *, email: str, password: str
    ) -> Optional[ClaimsPrincipal]:
        record = await self.store.find_by_provider("local", email)
        if record is None:
            return None
        user_id = record.get("user_id")
        if not user_id:
            return None

        pw_hash = await self.store.get_password_hash(user_id)
        if not pw_hash:
            return None

        try:
            self._hasher.verify(pw_hash, password)
        except VerifyMismatchError:
            return None
        except Exception:
            logger.warning("Unexpected argon2 verify error", exc_info=True)
            return None

        if self._hasher.check_needs_rehash(pw_hash):
            new_hash = self._hasher.hash(password)
            await self.store.set_password_hash(user_id, new_hash)

        return await self.principal_for_user(user_id)

    async def change_password(
        self, *, user_id: str, old_password: str, new_password: str
    ) -> bool:
        pw_hash = await self.store.get_password_hash(user_id)
        if not pw_hash:
            return False
        try:
            self._hasher.verify(pw_hash, old_password)
        except VerifyMismatchError:
            return False
        await self.store.set_password_hash(user_id, self._hasher.hash(new_password))
        return True

    async def reset_password(self, *, user_id: str, new_password: str) -> None:
        """Admin-side password reset (skips old-password check)."""
        await self.store.set_password_hash(user_id, self._hasher.hash(new_password))

    # --- Principal + token flows ---

    async def principal_for_user(self, user_id: str) -> Optional[ClaimsPrincipal]:
        record = await self.store.get_user(user_id)
        if record is None:
            return None
        return _principal_from_record(record, provider_prefix="local")

    def issue_id_token(
        self,
        *,
        user_id: str,
        claims: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        audience: Optional[str] = None,
    ) -> str:
        assert self.token_issuer is not None
        return self.token_issuer.issue(
            subject=user_id,
            audience=audience or self.audience,
            claims=claims,
            ttl=ttl,
        )

    def verify_id_token(
        self, token: str, *, audience: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        assert self.token_issuer is not None
        return self.token_issuer.verify(
            token, audience=audience or self.audience
        )

    async def principal_from_id_token(
        self, token: str
    ) -> Optional[ClaimsPrincipal]:
        payload = self.verify_id_token(token)
        if payload is None:
            return None
        user_id = str(payload.get("sub") or "")
        if not user_id:
            return None
        return await self.principal_for_user(user_id)


def _principal_from_record(
    record: Dict[str, Any], *, provider_prefix: str = "local"
) -> ClaimsPrincipal:
    user_id = str(record.get("user_id", ""))
    email = record.get("email")
    name = str(record.get("name") or email or "")
    claims: List[Claim] = [Claim(type="sub", value=user_id)]
    if email:
        claims.append(Claim(type="email", value=str(email)))
    for ctype, cvalue in (record.get("claims") or {}).items():
        claims.append(Claim(type=str(ctype), value=str(cvalue)))
    return ClaimsPrincipal(
        is_authenticated=True,
        name=name,
        user_id=f"{provider_prefix}:{user_id}" if user_id else "",
        claims=claims,
        raw=dict(record),
    )
