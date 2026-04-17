"""ClaimsPrincipal ⇄ session-dict serialization.

Auth state lives under the ``auth`` key of the PyWire session payload, the
same signed cookie used for page state. One cookie, one lifecycle, one
revocation path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pywire.auth.principal import Claim, ClaimsPrincipal

AUTH_KEY = "auth"


def serialize(principal: ClaimsPrincipal) -> Dict[str, Any]:
    return {
        "is_authenticated": principal.is_authenticated,
        "name": principal.name,
        "user_id": principal.user_id,
        "claims": [(c.type, c.value) for c in principal.claims],
        "raw": principal.raw,
    }


def deserialize(data: Dict[str, Any]) -> ClaimsPrincipal:
    return ClaimsPrincipal(
        is_authenticated=bool(data.get("is_authenticated", False)),
        name=str(data.get("name", "")),
        user_id=str(data.get("user_id", "")),
        claims=[Claim(type=t, value=v) for t, v in data.get("claims", [])],
        raw=dict(data.get("raw", {})),
    )


def read_principal_from_session(
    session: Optional[Dict[str, Any]],
) -> Optional[ClaimsPrincipal]:
    if not session:
        return None
    auth_data = session.get(AUTH_KEY)
    if not auth_data:
        return None
    return deserialize(auth_data)


def write_principal_to_session(
    session: Dict[str, Any], principal: ClaimsPrincipal
) -> None:
    session[AUTH_KEY] = serialize(principal)


def clear_principal_from_session(session: Dict[str, Any]) -> None:
    session.pop(AUTH_KEY, None)
