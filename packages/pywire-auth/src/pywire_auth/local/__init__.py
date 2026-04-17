"""Local identity provider — DB-backed, OIDC-native.

Issues its own signed id_tokens so downstream code treats a
password-authenticated user identically to an external OIDC login.
Users handle registration and login UI themselves; this module only
exposes backend APIs.

Usage:

    from pywire_auth import LocalIdP, MemoryAuthStore
    idp = LocalIdP(store=MemoryAuthStore(), secret="<long random>")
    user_id = await idp.create_user(email="a@b.c", password="hunter2")
    principal = await idp.verify_credentials(email="a@b.c", password="hunter2")
"""

from pywire_auth.local.idp import LocalIdP
from pywire_auth.local.token import TokenIssuer

__all__ = ["LocalIdP", "TokenIssuer"]
