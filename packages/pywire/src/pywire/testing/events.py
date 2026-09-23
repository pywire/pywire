"""Result wrapper for ``client.fire_event`` calls.

The dict returned by :meth:`pywire.runtime.page.BasePage.render_update`
has two shapes — a partial ``regions`` update or a full re-render. This
wrapper exposes both layouts behind one ergonomic surface so test code
can write ``result.regions`` or ``result.html`` without a
``result.get(...)`` dance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EventResult:
    """Outcome of a :meth:`TestClient.fire_event` call.

    Attributes:
        update_type: ``"regions"`` for partial updates, ``"full"`` for a
            full document re-render.
        regions: List of ``{"region": str, "html": str}`` dicts when
            ``update_type == "regions"``; empty list otherwise.
        html: Full document HTML when ``update_type == "full"``;
            ``None`` otherwise. For partial updates, see ``regions``.
        commands: Client-side commands the server emitted (set_cookie,
            navigate, etc.). Mostly empty in tests.
        meta: Update metadata (e.g. ``{"page_interactive": True}``).
        raw: The original dict from ``page.render_update`` — for
            assertions on keys not yet promoted to attributes.
    """

    update_type: str
    regions: list[dict[str, str]] = field(default_factory=list)
    html: Optional[str] = None
    commands: list[Any] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventResult":
        return cls(
            update_type=payload.get("type", ""),
            regions=list(payload.get("regions", [])),
            html=payload.get("html"),
            commands=list(payload.get("commands", [])),
            meta=dict(payload.get("meta", {})),
            raw=payload,
        )

    def region_html(self, region_id: str) -> Optional[str]:
        """Return the HTML for ``region_id`` or ``None`` if not present."""
        for entry in self.regions:
            if entry.get("region") == region_id:
                return entry.get("html")
        return None
