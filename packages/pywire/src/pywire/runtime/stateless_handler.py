"""POST endpoint for stateless (client-held state) mode.

Each event arrives with an HMAC-signed snapshot of the page state that the
client holds. The page is rebuilt per request — resolve route, instantiate,
restore state, re-resolve identity from the request (never from the client) —
dispatched through the standard ``handle_event`` path (which enforces the
compile-time ``__event_handlers__`` allowlist), then re-snapshotted.
"""

import asyncio
import logging
from typing import Any, Optional

import msgpack
from starlette.requests import Request
from starlette.responses import Response

from pywire.runtime.page_resolver import resolve_page
from pywire.runtime.protocol import build_update_payload
from pywire.runtime.session_serializer import restore_page_state
from pywire.runtime.snapshot_codec import (
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
        try:
            snapshot = decode_snapshot(
                data.get("snapshot", ""), secret=self.app._stateless_secret
            )
        except SnapshotError as exc:
            logger.warning("stateless: rejected snapshot: %s", exc)
            return self._err(400, "invalid snapshot")
        page = await self.build_page(request, data.get("path", "/"), snapshot)
        if page is None:
            return self._err(404, "no route")

        captured: list = []

        async def capture_update() -> None:
            captured.append(await page.render_update(init=False))

        page._on_update = capture_update
        pending = 0
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
                update = await page.handle_event(handler_name, data.get("data", {}))
            else:
                update = await page.render_update(init=False)
            nav = self._take_navigation(page)
            if nav is not None:  # handler called navigate()
                return nav

            # {$await} hold-open: drain background tasks up to the budget
            tasks = {t for t in page._background_tasks if not t.done()}
            if tasks:
                await asyncio.wait(tasks, timeout=self.app.await_budget)
                pending = sum(1 for t in tasks if not t.done())
                if captured:
                    update = self._merge_updates(update, captured)
        except ValueError as exc:
            # Allowlist rejection from _dispatch_handler (e.g. "render")
            logger.warning("stateless: rejected handler: %s", exc)
            return self._err(400, "invalid handler")
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
        payload.setdefault("meta", {})["pending_awaits"] = pending
        return self._msg(payload)

    @staticmethod
    def _take_navigation(page: Any) -> Optional[Response]:
        nav = getattr(page, "_pending_navigation", None)
        if not nav:
            return None
        page._pending_navigation = None
        return StatelessHandler._msg({"type": "navigate", "path": nav})

    @staticmethod
    def _merge_updates(base: dict, extras: list) -> dict:
        regions = {r["region"]: r["html"] for r in base.get("regions", [])}
        commands = list(base.get("commands", []))
        for upd in extras:
            for r in upd.get("regions", []):
                regions[r["region"]] = r["html"]
            commands.extend(upd.get("commands", []))
        merged = dict(base)
        merged["regions"] = [{"region": k, "html": v} for k, v in regions.items()]
        if commands:
            merged["commands"] = commands
        return merged

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
