"""Test client for PyWire apps.

:class:`TestClient` composes :class:`starlette.testclient.TestClient` —
HTTP requests pass through unchanged, exposed via ``.get()``,
``.post()``, etc. — and adds PyWire-aware helpers:

- :meth:`force_login` / :meth:`logout` mock ``app.get_user`` so any
  request inside the client's lifetime sees the chosen principal.
- :meth:`submit_form` wraps the ``X-PyWire-Handler`` header convention
  so callers don't have to remember it.
- :meth:`fire_event` drives an interactive-mode event handler directly
  against the page instance, returning an :class:`EventResult` —
  bypasses the WebSocket / msgpack roundtrip for speed.
- :meth:`select` runs a CSS selector against a response body and
  returns matched ``lxml`` elements.
- :meth:`session` exposes the live session-store dict for the active
  client cookie when running against a non-interactive app.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Union

from pywire.testing.events import EventResult


class TestClient:
    """Wraps :class:`starlette.testclient.TestClient` with PyWire helpers."""

    # Tells pytest not to try to collect this class as a test container
    # despite its "Test" prefix. (Same trick FastAPI's TestClient uses.)
    __test__ = False

    def __init__(
        self,
        app: Any,
        *,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = False,
    ) -> None:
        from starlette.testclient import TestClient as _StarletteTestClient

        self.app = app
        self._client = _StarletteTestClient(
            app,
            base_url=base_url,
            raise_server_exceptions=raise_server_exceptions,
        )
        self._original_get_user: Optional[Any] = None

    def __enter__(self) -> "TestClient":
        self._client.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._client.__exit__(*exc)
        # Restore patched get_user even if the test forgot to logout.
        if self._original_get_user is not None:
            self.app.get_user = self._original_get_user
            self._original_get_user = None

    # ---- HTTP proxy ----

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._client.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._client.post(url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._client.put(url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self._client.patch(url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._client.delete(url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._client.request(method, url, **kwargs)

    def websocket_connect(self, url: str, **kwargs: Any) -> Any:
        return self._client.websocket_connect(url, **kwargs)

    @property
    def cookies(self) -> Any:
        return self._client.cookies

    # ---- Auth mock ----

    def force_login(self, principal: Any) -> None:
        """Make every subsequent request see ``principal`` as the user.

        Monkeypatches ``app.get_user`` for the lifetime of this client
        (or until :meth:`logout` is called). Restores the original on
        ``__exit__`` regardless. The ``principal`` is typically a
        :class:`pywire.auth.ClaimsPrincipal` from :func:`make_principal`.
        """
        if self._original_get_user is None:
            self._original_get_user = self.app.get_user

        def _patched(_request_or_ws: Any) -> Any:
            return principal

        self.app.get_user = _patched

    def logout(self) -> None:
        """Restore the original ``app.get_user`` after :meth:`force_login`."""
        if self._original_get_user is not None:
            self.app.get_user = self._original_get_user
            self._original_get_user = None

    # ---- Form POST helper ----

    def submit_form(
        self,
        url: str,
        *,
        handler: str,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        spa: bool = False,
        **kwargs: Any,
    ) -> Any:
        """POST a form to a non-interactive page handler.

        Wraps the ``X-PyWire-Handler`` header convention. ``handler`` is
        the bare method name (e.g. ``"on_submit"``); component-scoped
        handlers should use the full ``_comp:{key}:{method}`` form.

        Set ``spa=True`` to send ``X-PyWire-Internal: form-submit`` so
        the server returns a body fragment instead of a full document.
        """
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-PyWire-Handler"] = handler
        if spa:
            headers["X-PyWire-Internal"] = "form-submit"
        return self._client.post(
            url,
            data=data or {},
            files=files,
            headers=headers,
            **kwargs,
        )

    # ---- Direct event firing (interactive WS-mode without WS) ----

    async def fire_event(
        self,
        url: str,
        *,
        handler: str,
        data: Optional[dict[str, Any]] = None,
        user: Any = None,
    ) -> EventResult:
        """Drive an event handler directly against a freshly resolved page.

        Bypasses the WebSocket protocol — instantiates the page via
        :func:`pywire.runtime.page_resolver.resolve_page`, applies
        ``page.user`` (from the active :meth:`force_login` if any, or
        the explicit ``user`` argument), and calls
        :meth:`page.handle_event`.

        Returns an :class:`EventResult` wrapping the dict from
        :meth:`render_update`. The page instance is discarded after the
        call — there is no implicit state continuity across multiple
        ``fire_event`` calls. Tests that need that should use the
        WebSocket transport via :meth:`websocket_connect`.
        """
        from pywire.runtime.page_resolver import resolve_page

        resolved = resolve_page(self.app.router, url)
        if resolved is None:
            raise LookupError(f"No page matches {url!r}")
        page, _params, _variant = resolved

        # Wire the app reference through scope so render() reaches its
        # state bag the same way the server does.
        page.request.scope["app"] = self.app.app

        if user is not None:
            page.user = user
        elif self._original_get_user is not None:
            # force_login is active; honor it.
            page.user = self.app.get_user(page.request)

        await page.render(init=True)
        payload = await page.handle_event(handler, data or {})
        return EventResult.from_dict(payload)

    # ---- Session access ----

    @contextmanager
    def session(self) -> Iterator[dict[str, Any]]:
        """Yield the live session dict for the current client cookie.

        Only meaningful when the underlying app uses
        ``interactive_server_mode=False`` (so :class:`SessionMiddleware`
        is installed). Mutations are written back when the context
        block exits.

        Example::

            with client.session() as sess:
                sess["custom"] = "value"
        """
        store = getattr(self.app, "session_store", None)
        if store is None:
            raise RuntimeError(
                "TestClient.session() requires an app with a session_store; "
                "either pass session_store=MemorySessionStore() to PyWire(...) "
                "or use interactive_server_mode=False."
            )

        cookie = self._client.cookies.get("pywire_session")
        if cookie is None:
            raise RuntimeError(
                "No pywire_session cookie set yet — make at least one request "
                "before opening client.session()."
            )

        # The signed cookie shape is "{session_id}.{hmac_prefix}". Tests
        # have already proved the signature when the cookie reached the
        # client; re-verifying would require knowing the auto-generated
        # SessionMiddleware secret, which PyWire doesn't surface. So we
        # parse the session id structurally — if the cookie was tampered
        # with, the test will see whatever data the (untampered) request
        # cycle produced anyway.
        if "." not in cookie:
            raise RuntimeError("pywire_session cookie has unexpected shape.")
        sid = cookie.rsplit(".", 1)[0]

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(store.get(sid)) or {}
            data = dict(data)
            yield data
            loop.run_until_complete(store.set(sid, data))
        finally:
            loop.close()

    # ---- HTML selection ----

    def select(self, response: Any, css: str) -> list[Any]:
        """Run a CSS selector against an HTTP response body.

        Returns a list of ``lxml.html.HtmlElement`` matches. ``response``
        is anything with a ``.text`` or ``.body`` attribute.
        """
        from lxml import html as lxml_html

        body = self._extract_body(response)
        if not body:
            return []
        tree = lxml_html.fromstring(body)
        return list(tree.cssselect(css))

    @staticmethod
    def _extract_body(response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        body: Union[bytes, bytearray, str, None] = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body).decode("utf-8", errors="replace")
        if isinstance(body, str):
            return body
        return ""
