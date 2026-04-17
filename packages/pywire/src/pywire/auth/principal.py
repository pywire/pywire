"""Claims-based principal representation.

``ClaimsPrincipal`` is the unified identity object PyWire passes between
transports, pages, policies, and the auth channel. External OIDC providers
and the local IdP both produce a ``ClaimsPrincipal`` — downstream code is
provider-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Claim:
    """A single (type, value) claim. Immutable by construction."""

    type: str
    value: str


@dataclass
class ClaimsPrincipal:
    """A unified identity object.

    Construct via providers or build directly in tests. Use ``ANONYMOUS``
    for unauthenticated placeholder — avoids ``Optional[ClaimsPrincipal]``
    sprinkled through the codebase.
    """

    is_authenticated: bool = False
    name: str = ""
    user_id: str = ""
    claims: List[Claim] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def has_claim(self, type: str, value: Optional[str] = None) -> bool:
        """True if principal has a claim of ``type``.

        If ``value`` is given, also requires an exact value match.
        """
        for c in self.claims:
            if c.type != type:
                continue
            if value is None or c.value == value:
                return True
        return False

    def claim_value(self, type: str) -> Optional[str]:
        """First value for the given claim type, or None."""
        for c in self.claims:
            if c.type == type:
                return c.value
        return None


ANONYMOUS: ClaimsPrincipal = ClaimsPrincipal()
