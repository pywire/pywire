"""Cloudflare Durable Object for PyWire WebSocket sessions.

Each session gets its own DO instance. The DO:
- Accepts WebSocket connections via the hibernation API
- Handles the PyWire WS protocol (init, event, relocate, ref_sync)
- Persists page state in DO transactional storage
- Hibernates between messages (no billing for idle time)

This module is NOT imported directly — it's used as a template by the deploy CLI
to generate a project-specific pywire_do.py that imports the user's app.
"""

# NOTE: This file serves as the reference implementation. The deploy CLI
# generates a standalone pywire_do.py from CF_DURABLE_OBJECT_TEMPLATE in deploy.py,
# which is a string template parameterized by the user's app import.
# This file exists for documentation and testing purposes.

from __future__ import annotations

from typing import Any, Dict, Optional, cast
from urllib.parse import parse_qs, urlparse


def _make_request(pathname: str, query_string: str = "") -> Any:
    """Create a minimal Starlette Request for page instantiation."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "path": pathname,
        "raw_path": pathname.encode("ascii"),
        "query_string": query_string.encode("ascii") if query_string else b"",
        "headers": [(b"host", b"localhost")],
        "method": "GET",
        "scheme": "https",
        "server": ("localhost", 443),
        "root_path": "",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _parse_query(query_string: str) -> Dict[str, Any]:
    """Parse query string into a flat dict."""
    if not query_string:
        return {}
    parsed = parse_qs(query_string)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _build_path_info(page_class: Any, variant_name: Optional[str]) -> Dict[str, bool]:
    """Build path variant info dict for page constructor."""
    path_info: Dict[str, bool] = {}
    if hasattr(page_class, "__routes__"):
        for name in page_class.__routes__.keys():
            path_info[name] = name == variant_name
    elif hasattr(page_class, "__route__"):
        path_info["main"] = True
    return path_info


def _build_url_helper(page_class: Any) -> Any:
    """Build URLHelper if page has named routes."""
    if hasattr(page_class, "__routes__") and page_class.__routes__:
        from pywire.runtime.router import URLHelper

        return URLHelper(page_class.__routes__)
    return None


def _instantiate_page(app: Any, pathname: str, query_string: str = "") -> Any:
    """Match route and instantiate a page for the given path.

    Returns (page, page_class) or raises ValueError if no route matches.
    """
    parsed = urlparse(pathname)
    clean_path = parsed.path
    qs = parsed.query or query_string

    match = app.router.match(clean_path)
    if not match:
        raise ValueError(f"No route found for path: {clean_path}")

    page_class, params, variant_name = match
    request = _make_request(clean_path, qs)
    query = _parse_query(qs)
    path_info = _build_path_info(page_class, variant_name)
    url_helper = _build_url_helper(page_class)

    page = page_class(
        request=request,
        params=params,
        query=query,
        path=path_info,
        url=url_helper,
    )
    return page


def _send_update(ws: Any, update: Any) -> None:
    """Send a page update to the client over WebSocket.

    Handles both full HTML responses and regional updates.
    Uses JSON encoding (CF Workers WS API).
    """
    import json

    from starlette.responses import Response

    if isinstance(update, Response):
        html = cast(bytes, update.body).decode("utf-8")
        ws.send(json.dumps({"type": "update", "html": html}))
        return

    if isinstance(update, dict):
        msg_type = update.get("type")
        if msg_type == "regions":
            payload: Dict[str, Any] = {
                "type": "update",
                "regions": update.get("regions", []),
            }
            if "commands" in update:
                payload["commands"] = update["commands"]
            ws.send(json.dumps(payload))
            return
        if msg_type == "full":
            payload = {"type": "update", "html": update.get("html", "")}
            if "commands" in update:
                payload["commands"] = update["commands"]
            ws.send(json.dumps(payload))
            return

    # Fallback: force full reload
    ws.send(json.dumps({"type": "reload"}))
