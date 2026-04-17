"""Per-request auth envelope.

``AuthContext`` is set by the auth middleware / WS handler before page code
runs and cleared after. The guard reads it via ``get_auth_context()`` to
find the policy engine and channel without leaking a global import graph
into ``page.py``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

from pywire.auth.channel import AuthChannel
from pywire.auth.policy import PolicyEngine
from pywire.auth.principal import ClaimsPrincipal


@dataclass
class AuthContext:
    principal: ClaimsPrincipal
    engine: PolicyEngine
    channel: AuthChannel


_auth_ctx: ContextVar[Optional[AuthContext]] = ContextVar(
    "pywire_auth_ctx", default=None
)


def get_auth_context() -> Optional[AuthContext]:
    return _auth_ctx.get()


def set_auth_context(ctx: AuthContext) -> Token[Optional[AuthContext]]:
    return _auth_ctx.set(ctx)


def reset_auth_context(token: Token[Optional[AuthContext]]) -> None:
    _auth_ctx.reset(token)
