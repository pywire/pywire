"""Direct render helpers — bypass HTTP entirely for speed.

These are the fastest path for pure render assertions. Use them when a
test only needs to inspect rendered HTML and doesn't care about the
full request/response cycle (cookies, middleware, sessions).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def response_to_html(response: Any) -> str:
    """Decode a Starlette/httpx response body to ``str``.

    Used by both :class:`TestClient.select` (over httpx ``Response``
    instances, which expose ``.text``) and the direct render helpers
    (over Starlette ``Response`` instances, which expose ``.body``).
    """
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body).decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    return ""


async def render_page(
    app: Any,
    path: str,
    *,
    user: Any = None,
) -> str:
    """Resolve a path to a page and return its rendered HTML.

    Skips the Starlette test client entirely — instantiates the page
    via :func:`pywire.runtime.page_resolver.resolve_page`, optionally
    sets ``page.user``, and calls ``await page.render()``.
    """
    from pywire.runtime.page_resolver import resolve_page

    resolved = resolve_page(app.router, path)
    if resolved is None:
        raise LookupError(f"No page matches {path!r}")
    page, _params, _variant = resolved

    page.request.scope["app"] = app.app
    if user is not None:
        page.user = user

    response = await page.render(init=True)
    return response_to_html(response)


async def render_component(
    component_class: type,
    *,
    request: Any = None,
    init: bool = False,
    **props: Any,
) -> str:
    """Render a component standalone and return its HTML.

    ``component_class`` is a compiled component (a :class:`BasePage`
    subclass with ``__is_component__`` semantics). Props passed as
    keyword arguments are applied via ``_update_props`` when the class
    exposes it (the path the parent-renders-child machinery uses), so
    typed / validated props are coerced normally; otherwise they are
    set directly with ``setattr``.

    A minimal mock :class:`Request` is built when ``request`` is None;
    pass an explicit one when component code reads request fields.
    """
    if request is None:
        request = _mock_request()

    instance = component_class(
        request=request,
        params={},
        query={},
        __is_component__=True,
    )
    update_props = getattr(instance, "_update_props", None)
    if callable(update_props):
        update_props(props)
    else:
        for key, value in props.items():
            setattr(instance, key, value)

    response = await instance.render(init=init)
    return response_to_html(response)


def _mock_request() -> Any:
    """Build a stand-in :class:`Request` shape for direct component renders.

    The real :class:`render` walks ``request.app.state`` for several
    feature flags but the lookups are all guarded with try/except, so a
    bare mock works fine.
    """
    request = MagicMock()
    request.scope = {
        "type": "http",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "method": "GET",
    }
    request.url.path = "/"
    request.app.state = MagicMock()
    return request
