"""Who is asking.

Pages get a ``ClaimsPrincipal`` from the session cookie (pywire-auth puts it
on ``self.user``). The JSON API takes a bearer token instead, so it needs no
cookies and no CSRF protection. Both turn into an ``Actor``, which is all
``services`` ever sees.

Authorization never reads claims from pywire-auth's LocalIdP registration:
board roles live in our own ``memberships`` table. (LocalIdP's register
route currently accepts a ``role`` claim from the form, so a claim-based
check would be forgeable. Keep authorization data in your own tables.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pywire_auth import LocalIdP, SQLAlchemyAuthStore

from taskboard import db
from taskboard.errors import NotAuthenticated
from taskboard.settings import settings

store = SQLAlchemyAuthStore(db.engine)
idp = LocalIdP(store=store, secret=settings.idp_secret)

API_TOKEN_TTL = 3600
SOCKET_AUDIENCE = "taskboard-cursors"
SOCKET_TOKEN_TTL = 300


@dataclass(frozen=True)
class Actor:
    id: str  # pywire-auth principal id, e.g. "local:3f0c..."
    name: str


def actor_from(principal: Any) -> Actor:
    if principal is None or not getattr(principal, "is_authenticated", False):
        raise NotAuthenticated("Sign in first")
    return Actor(id=principal.user_id, name=principal.name or "Someone")


def api_token(actor: Actor) -> str:
    """A bearer token for the JSON API, for this user."""
    subject = actor.id.split(":", 1)[-1]  # LocalIdP tokens carry the bare id
    return idp.issue_id_token(user_id=subject, ttl=API_TOKEN_TTL)


async def actor_from_token(token: str) -> Actor:
    principal = await idp.principal_from_id_token(token)
    return actor_from(principal)


def socket_token(actor: Actor, board_id: int) -> str:
    """Short-lived ticket for one board's cursor socket.

    Browsers can't set headers on a WebSocket, and the page's own session
    cookie isn't read by FastAPI routes, so the page mints a ticket scoped to
    one board and renders it into the HTML for its script to use.
    """
    return idp.issue_id_token(
        user_id=actor.id,
        claims={"name": actor.name, "board": board_id},
        ttl=SOCKET_TOKEN_TTL,
        audience=SOCKET_AUDIENCE,
    )


def actor_from_socket_token(token: str, board_id: int) -> Actor | None:
    payload = idp.verify_id_token(token, audience=SOCKET_AUDIENCE)
    if not payload or payload.get("board") != board_id:
        return None
    return Actor(id=str(payload["sub"]), name=str(payload.get("name") or "Someone"))
