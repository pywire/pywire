"""Resolve a URL path to a live Page instance.

Shared between WebSocketHandler (standard server) and the Durable Object
template (CF Workers). Eliminates duplicated page-instantiation logic.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request

from pywire.runtime.router import URLHelper


def resolve_page(
    router: Any,
    path: str,
    *,
    base_scope: Optional[dict[str, Any]] = None,
) -> Optional[tuple[Any, dict[str, Any], str]]:
    """Match a URL path against the router and instantiate the page.

    Args:
        router: The app's Router instance.
        path: URL path, optionally including query string.
        base_scope: ASGI scope to extend (e.g. from an existing WebSocket).
            If ``None``, a minimal synthetic scope is created — used by
            environments without a real HTTP connection (CF Workers DO).

    Returns:
        ``(page, params, variant_name)`` on success, or ``None`` if no
        route matches.
    """
    parsed = urlparse(path)
    pathname = parsed.path
    qs = parsed.query

    match = router.match(pathname)
    if not match:
        return None

    page_class, params, variant_name = match

    # Build ASGI scope
    scope: dict[str, Any] = dict(base_scope) if base_scope else {}
    scope.update(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "path": pathname,
            "raw_path": pathname.encode("ascii"),
            "query_string": qs.encode("ascii") if qs else b"",
        }
    )
    scope.setdefault("headers", [(b"host", b"localhost")])
    scope.setdefault("method", "GET")
    scope.setdefault("scheme", "https")
    scope.setdefault("server", ("localhost", 443))
    scope.setdefault("root_path", "")
    scope.setdefault("client", ("127.0.0.1", 0))

    request = Request(scope)
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
    return page, params, variant_name


def _parse_query(qs: str) -> dict[str, Any]:
    if not qs:
        return {}
    parsed = parse_qs(qs)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _build_path_info(page_class: Any, variant_name: str) -> dict[str, bool]:
    path_info: dict[str, bool] = {}
    if hasattr(page_class, "__routes__"):
        for name in page_class.__routes__.keys():
            path_info[name] = name == variant_name
    elif hasattr(page_class, "__route__"):
        path_info["main"] = True
    return path_info


def _build_url_helper(page_class: Any) -> Optional[URLHelper]:
    if hasattr(page_class, "__routes__") and page_class.__routes__:
        return URLHelper(page_class.__routes__)
    return None
