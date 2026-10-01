"""POST endpoint for stateless (client-held state) mode.

Each event arrives with an HMAC-signed snapshot of the page state that the
client holds. The page is rebuilt per request — resolve route, instantiate,
restore state, re-resolve identity from the request (never from the client) —
dispatched through the standard ``handle_event`` path (which enforces the
compile-time ``__event_handlers__`` allowlist), then re-snapshotted.
"""

import hashlib
import logging
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import urlsplit

import msgpack
from starlette.requests import Request
from starlette.responses import Response

from pywire.core.wire import WireBase
from pywire.runtime.page_resolver import resolve_page
from pywire.runtime.protocol import build_update_payload
from pywire.runtime.session_serializer import restore_page_state
from pywire.runtime.subscriptions import restore_subscriptions
from pywire.runtime.snapshot_codec import (
    MAX_SNAPSHOT_LEN,
    SnapshotError,
    decode_snapshot,
    encode_snapshot,
    snapshot_route,
)

logger = logging.getLogger(__name__)


def _drop_unchanged_live(
    update: Dict[str, Any],
    live: Set[Optional[str]],
    shown: Any,
) -> Dict[str, str]:
    """Drop re-rendered shared-state regions the client already shows.

    ``shown`` is the region -> HTML digest map from the client's snapshot.
    Every shared-state region is re-rendered on every request, so the map
    returned here (for the next snapshot) is exactly what the client shows
    once it applies ``update``. A full-page update carries no per-region
    HTML: start over, and the next request sends every region once.
    """
    if update.get("type") != "regions":
        return {}
    digests: Dict[str, str] = dict(shown) if isinstance(shown, dict) else {}
    kept = []
    for entry in update.get("regions", []):
        region = entry.get("region") if isinstance(entry, dict) else None
        html = entry.get("html") if isinstance(entry, dict) else None
        if region in live and isinstance(region, str) and isinstance(html, str):
            digest = hashlib.blake2b(html.encode("utf-8"), digest_size=8).hexdigest()
            if digests.get(region) == digest:
                continue
            digests[region] = digest
        kept.append(entry)
    update["regions"] = kept
    return {r: d for r, d in digests.items() if r in live}


class StatelessHandler:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._shared_write_warned: Set[str] = set()

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
        # CSRF: snapshots aren't bound to a user, so a cross-site page could
        # mint one and make a victim's browser post it with their cookies.
        # A form or no-cors fetch can't send this content type, and a CORS
        # fetch that does needs a preflight this endpoint never answers.
        content_type = request.headers.get("content-type", "")
        if content_type.split(";")[0].strip().lower() != "application/x-msgpack":
            return self._err(415, "expected application/x-msgpack")
        if request.headers.get("sec-fetch-site", "same-origin") not in (
            "same-origin",
            "none",
        ):
            return self._err(403, "cross-site request")
        # Defense in depth: a declared length over the snapshot cap cannot
        # hold a valid request — reject before buffering the body at all.
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_SNAPSHOT_LEN + 2048:
            return self._err(413, "request body too large")
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
        # The snapshot only rebuilds the page it was rendered for. Replayed
        # against another path or query, it would run that page's handlers
        # with @before_load/@init skipped (they don't re-run on events),
        # bypassing any authorization they perform.
        parts = urlsplit(path)
        route = snapshot_route(parts.path, parts.query)
        if snapshot.get("route") != route:
            logger.warning("stateless: snapshot not issued for %r", path)
            return self._err(400, "invalid snapshot")
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

        handler_name = data.get("handler")
        try:
            # render_update emits region diffs only for wires mapped to the
            # regions that read them, and a fresh page has no such map. The
            # snapshot carries it; otherwise a discarded render registers it
            # (WS-connect parity). A component event needs its component,
            # which only a render builds. init=False skips @init/@before_load
            # hooks — state comes from the snapshot.
            subs = snapshot.get("subs")
            skip_render = (
                subs is not None
                and not str(handler_name or "").startswith("_comp:")
                and restore_subscriptions(page, subs)
            )
            if skip_render:
                await page._run_auth_guard()
            else:
                await page.render(init=False)
            nav = self._take_navigation(page)
            if nav is not None:  # auth guard rejected the rebuilt page
                return nav

            # Shared state (module wires, producers) may have changed since
            # the client's last request, and nothing here marks it dirty:
            # re-render the regions that show it on every request.
            live = page._live_regions()
            page._dirty_regions.update(live)
            shared_seqs = self._shared_write_seqs(page)

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

        self._warn_shared_writes(page, shared_seqs)
        live_digests = _drop_unchanged_live(update, live, snapshot.get("live"))
        payload = build_update_payload(update)
        payload["live_every"] = self.app._live_every_ms(page, strict=False)
        payload["snapshot"] = encode_snapshot(
            page,
            secret=self.app._stateless_secret,
            route=route,
            warn_size=self.app.session_warn_size,
            live=live_digests,
            components=snapshot.get("component_snapshots") if skip_render else None,
        )
        return self._msg(payload)

    @staticmethod
    def _shared_write_seqs(page: Any) -> Dict[int, Tuple[Any, int]]:
        return {
            id(source): (source, source._write_seq)
            for source in page._shared_sources()
            if isinstance(source, WireBase)
        }

    def _warn_shared_writes(
        self, page: Any, before: Dict[int, Tuple[Any, int]]
    ) -> None:
        """Warn once when an event writes shared state in a stateless app.

        Each server instance (and each FaaS isolate) has its own copy of a
        module-level wire, so the write is invisible to users served by any
        other instance, and lost on a cold start.
        """
        written = [s for s, seq in before.values() if s._write_seq != seq]
        key = type(page).__qualname__
        if not written or key in self._shared_write_warned:
            return
        self._shared_write_warned.add(key)
        logger.warning(
            "stateless: %s wrote shared state. Each server instance keeps its "
            "own copy of module-level state, so users served by another "
            "instance won't see the change and a restart loses it. Keep state "
            "that users share in a database or key-value store.",
            getattr(page, "__file_path__", key),
        )

    @staticmethod
    def _refused(page: Any, handler_name: str) -> bool:
        """True when dispatch must be refused per ``__event_handlers__``.

        Mirrors ``BasePage._dispatch_handler`` allowlist semantics (None =
        permissive hand-rolled) for both page-level and ``_comp:`` names,
        walking nested components (``_comp:<layout>:_comp:<Nav>:bump``) the
        same way ``_handle_component_event`` dispatches them.
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
            return StatelessHandler._refused(component, remainder)
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
