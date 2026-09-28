"""Wire protocol helpers shared between transport implementations.

Used by both WebSocketHandler (standard server) and the Durable Object
template (CF Workers) to avoid duplicating message construction logic.
"""

from __future__ import annotations

from typing import Any


def build_update_payload(update: Any) -> dict[str, Any]:
    """Convert a page render update into a wire-protocol message dict.

    Accepts the return value of ``page.render_update()`` or ``page.render()``
    and returns a dict ready for msgpack encoding and transmission.
    """
    from starlette.responses import Response

    if isinstance(update, Response):
        html = (
            update.body.decode("utf-8")
            if isinstance(update.body, bytes)
            else update.body
        )
        return {"type": "update", "html": html}

    if isinstance(update, dict):
        if update.get("type") == "regions":
            payload: dict[str, Any] = {
                "type": "update",
                "regions": update.get("regions", []),
            }
            if "commands" in update:
                payload["commands"] = update["commands"]
            return payload
        if update.get("type") == "full":
            payload = {"type": "update", "html": update.get("html", "")}
            if "commands" in update:
                payload["commands"] = update["commands"]
            return payload

    # Fallback: force full reload
    return {"type": "reload"}


def event_ack(message: dict[str, Any]) -> int | None:
    """The id of a client event message, to echo back as ``ack``.

    The client numbers its events and settles each optimistic prediction when
    the reply carrying that event's id arrives. Non-int ids are ignored.
    """
    ack = message.get("id")
    return ack if isinstance(ack, int) and not isinstance(ack, bool) else None


def with_ack(payload: dict[str, Any], ack: int | None) -> dict[str, Any]:
    """Mark ``payload`` as the reply to client event ``ack`` (if known)."""
    if ack is not None:
        payload["ack"] = ack
    return payload
