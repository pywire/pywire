"""PyWire auth primitives.

Core abstractions shared by ``pywire-auth`` (OIDC providers, local IdP,
database adapters) and the runtime. This module deliberately has zero
dependencies on Starlette-level auth plumbing so it can be imported
during codegen and at test time.
"""

from pywire.auth.channel import (
    AuthChannel,
    AuthEvent,
    AuthSubscription,
    MemoryAuthChannel,
)
from pywire.auth.context import (
    AuthContext,
    get_auth_context,
    reset_auth_context,
    set_auth_context,
)
from pywire.auth.guard import evaluate_auth, run_auth_guard
from pywire.auth.policy import (
    Policy,
    PolicyContext,
    PolicyDeniedError,
    PolicyEngine,
    PolicyLike,
)
from pywire.auth.principal import ANONYMOUS, Claim, ClaimsPrincipal
from pywire.auth.session import (
    AUTH_KEY,
    clear_principal_from_session,
    deserialize,
    read_principal_from_session,
    serialize,
    write_principal_to_session,
)

__all__ = [
    "ANONYMOUS",
    "AUTH_KEY",
    "AuthChannel",
    "AuthContext",
    "AuthEvent",
    "AuthSubscription",
    "Claim",
    "ClaimsPrincipal",
    "MemoryAuthChannel",
    "Policy",
    "PolicyContext",
    "PolicyDeniedError",
    "PolicyEngine",
    "PolicyLike",
    "clear_principal_from_session",
    "deserialize",
    "evaluate_auth",
    "get_auth_context",
    "read_principal_from_session",
    "reset_auth_context",
    "run_auth_guard",
    "serialize",
    "set_auth_context",
    "write_principal_to_session",
]
