"""Dispatch custom DOM events from Python."""

from contextvars import ContextVar
from typing import Any, Optional

from pywire.core.wire import _render_context

# Separate context for the current page during event handler execution.
# Unlike _render_context (which is for wire dependency tracking during render),
# this is safe to set during handlers without triggering spurious dirty regions.
_page_context: ContextVar[Any] = ContextVar("pywire_page_context", default=None)


def _get_current_page() -> Any:
    """Return the current page from either the handler or render context."""
    page = _page_context.get()
    if page is not None:
        return page

    ctx = _render_context.get()
    if ctx is not None:
        return ctx[0]

    return None


def dispatch(
    event_name: str,
    *,
    detail: Optional[dict[str, Any]] = None,
    bubbles: bool = True,
    target_ref: Any = None,
) -> None:
    """Dispatch a custom DOM event on the client.

    Args:
        event_name: The name of the custom event (e.g. ``"item-selected"``).
        detail: Optional detail payload attached to the ``CustomEvent``.
        bubbles: Whether the event bubbles up through the DOM. Defaults to ``True``.
        target_ref: An optional ref object. When provided the event is dispatched
            on that element; otherwise it is dispatched on ``document.body``.
    """
    page = _get_current_page()
    if page is None:
        raise RuntimeError(
            "dispatch() must be called during a page render or event handler"
        )

    # Server-side interception: when called from a handler context (not render),
    # the target ref has a registered pywire handler for this event, and bubbling
    # is disabled, call the handler directly on the server — no DOM round trip
    # for the pywire handler.  The dispatch command is still sent to the client
    # so that any JS listeners fire with the correct detail, but it is marked
    # ``serverHandled`` so the client won't re-send it back to the server.
    server_handled = False
    if target_ref is not None and not bubbles and _page_context.get() is not None:
        handler_name = getattr(target_ref, "_event_handlers", {}).get(event_name)
        if handler_name:
            handler_page = getattr(target_ref, "_page", None) or page
            handler_page._pending_intercepted_handlers.append(
                (handler_name, {"detail": detail or {}})
            )
            server_handled = True

    ref_id: Optional[str] = None
    if target_ref is not None:
        ref_id = getattr(target_ref, "_ref_id", None)

    command: dict[str, Any] = {
        "cmd": "dispatch",
        "event": event_name,
        "detail": detail,
        "bubbles": bubbles,
        "refId": ref_id,
    }
    if server_handled:
        command["serverHandled"] = True

    page._pending_dispatches.append(command)
