"""POST endpoint for stateless (client-held state) mode.

Each event arrives with an HMAC-signed snapshot of the page state that the
client holds. The page is rebuilt per request — resolve route, instantiate,
restore state, re-resolve identity from the request (never from the client) —
dispatched through the standard ``handle_event`` path (which enforces the
compile-time ``__event_handlers__`` allowlist), then re-snapshotted.
"""

import logging
from typing import Any, Optional

import msgpack
from starlette.requests import Request
from starlette.responses import Response

from pywire.runtime.page_resolver import resolve_page
from pywire.runtime.protocol import build_update_payload
from pywire.runtime.session_serializer import restore_page_state
from pywire.runtime.snapshot_codec import (
    MAX_SNAPSHOT_LEN,
    SnapshotError,
    decode_snapshot,
    encode_snapshot,
)

logger = logging.getLogger(__name__)


class StatelessHandler:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def build_page(
        self, request: Request, path: str, snapshot: dict
    ) -> Optional[Any]:
        """Resolve, instantiate, restore state, re-resolve user from request."""
        result = resolve_page(self.app.router, path, base_scope=dict(request.scope))
        if result is None:
            return None
        page, _params, _variant_name = result
        snapshot.pop("user", None)  # defense in depth: identity never from client
        restore_page_state(page, snapshot)
        # Identity ALWAYS from the request (middleware/session), never the client
        resolved_user = self.app._resolve_user_for_request(request)
        if resolved_user is not None:
            page.user = resolved_user
        return page

    async def handle_event(self, request: Request) -> Response:
        try:
            data = msgpack.unpackb(await request.body(), raw=False)
            if not isinstance(data, dict):
                raise ValueError("body is not a mapping")
        except Exception:
            return self._err(400, "malformed request body")
        snap_blob = data.get("snapshot", "")
        if not isinstance(snap_blob, str):
            return self._err(400, "invalid snapshot")
        # Ceiling before decode — an oversized blob must be a cheap reject,
        # not a base64/HMAC/msgpack burn.
        if len(snap_blob) > MAX_SNAPSHOT_LEN:
            return self._err(413, "snapshot too large")
        try:
            snapshot = decode_snapshot(snap_blob, secret=self.app._stateless_secret)
        except SnapshotError as exc:
            logger.warning("stateless: rejected snapshot: %s", exc)
            return self._err(400, "invalid snapshot")
        path = data.get("path", "/")
        if not isinstance(path, str):
            return self._err(400, "invalid path")
        event_data = data.get("data", {})
        if not isinstance(event_data, dict):
            return self._err(400, "invalid data")
        try:
            page = await self.build_page(request, path, snapshot)
        except Exception as exc:
            # A stale snapshot (e.g. signed before a deploy) or unrestorable
            # state is a client fault: 400, never a crash.
            logger.warning("stateless: page rebuild failed: %s", exc)
            return self._err(400, "invalid snapshot")
        if page is None:
            return self._err(404, "no route")

        try:
            # WS-connect parity: a discarded render registers wire→region
            # subscriptions; without it render_update cannot emit region diffs
            # (fresh page has no _wire_subscribers yet). init=False skips
            # @init/@before_load hooks — state comes from the snapshot.
            await page.render(init=False)
            nav = self._take_navigation(page)
            if nav is not None:  # auth guard rejected the rebuilt page
                return nav

            handler_name = data.get("handler")
            if handler_name:
                # Pre-check the allowlist (like _handle_form_post) so probing
                # clients get a clean 400 while business ValueErrors raised
                # inside handlers stay 500s with logger.exception.
                if not isinstance(handler_name, str) or self._refused(
                    page, handler_name
                ):
                    logger.warning("stateless: rejected handler: %r", handler_name)
                    return self._err(400, "invalid handler")
                update = await page.handle_event(handler_name, event_data)
            else:
                update = await page.render_update(init=False)
            nav = self._take_navigation(page)
            if nav is not None:  # handler called navigate()
                return nav
        except Exception:
            logger.exception("stateless: event failed")
            return self._err(500, "event failed")
        finally:
            for t in page._background_tasks:
                if not t.done():
                    t.cancel()

        payload = build_update_payload(update)
        payload["snapshot"] = encode_snapshot(
            page,
            secret=self.app._stateless_secret,
            warn_size=self.app.session_warn_size,
        )
        return self._msg(payload)

    @staticmethod
    def _refused(page: Any, handler_name: str) -> bool:
        """True when dispatch must be refused per ``__event_handlers__``.

        Mirrors ``BasePage._dispatch_handler`` allowlist semantics (None =
        permissive hand-rolled) for both page-level and ``_comp:`` names.
        """
        if handler_name.startswith("_comp:"):
            comp_key, sep, remainder = handler_name[len("_comp:") :].partition(":")
            component = (
                page._components.get(comp_key)
                if sep and comp_key and remainder
                else None
            )
            if component is None:
                return True
            allowed = component.__class__.__event_handlers__
            return allowed is not None and remainder not in allowed
        allowed = page.__class__.__event_handlers__
        return allowed is not None and handler_name not in allowed

    @staticmethod
    def _take_navigation(page: Any) -> Optional[Response]:
        nav = getattr(page, "_pending_navigation", None)
        if not nav:
            return None
        page._pending_navigation = None
        return StatelessHandler._msg({"type": "navigate", "path": nav})

    @staticmethod
    def _msg(payload: dict) -> Response:
        return Response(msgpack.packb(payload), media_type="application/x-msgpack")

    @staticmethod
    def _err(status: int, msg: str) -> Response:
        return Response(
            msgpack.packb({"error": msg}),
            status_code=status,
            media_type="application/x-msgpack",
        )
