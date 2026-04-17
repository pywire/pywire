"""Tests for the dev-only SSE reload channel (non-interactive mode)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from pywire.runtime.app import PyWire
from pywire.runtime.dev_reload import DevReloadBroadcaster


def _make_non_interactive_app() -> PyWire:
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.wire").write_text("<p>Home</p>")
    app = PyWire(pages_dir=str(pages_dir), interactive_server_mode=False)
    app._test_dir = test_dir
    return app


# ---------------------------------------------------------------------------
# DevReloadBroadcaster unit tests
# ---------------------------------------------------------------------------


class TestDevReloadBroadcaster:
    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast_reload(self):
        b = DevReloadBroadcaster()
        q = await b.subscribe()
        await b.broadcast_reload()
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        assert "event: reload" in msg
        assert '"type": "reload"' in msg

    @pytest.mark.asyncio
    async def test_broadcast_shutdown(self):
        b = DevReloadBroadcaster()
        q = await b.subscribe()
        await b.broadcast_shutdown()
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        assert "event: shutdown" in msg

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self):
        b = DevReloadBroadcaster()
        q1 = await b.subscribe()
        q2 = await b.subscribe()
        await b.broadcast_reload()
        m1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        m2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert "reload" in m1 and "reload" in m2

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        b = DevReloadBroadcaster()
        q = await b.subscribe()
        await b.unsubscribe(q)
        await b.broadcast_reload()
        assert q.empty()

    @pytest.mark.asyncio
    async def test_no_subscribers_is_noop(self):
        b = DevReloadBroadcaster()
        # Must not raise with zero subscribers.
        await b.broadcast_reload()
        await b.broadcast_shutdown()

    @pytest.mark.asyncio
    async def test_slow_subscriber_does_not_block(self):
        b = DevReloadBroadcaster()
        q = await b.subscribe()
        # Fill beyond maxsize.
        for _ in range(20):
            await b.broadcast_reload()
        # Broadcast returned normally even though queue was full — slow
        # subscribers just drop frames.
        assert q.qsize() <= 8


# ---------------------------------------------------------------------------
# dev_server guard regression — simulate the watcher and shutdown paths
# with a non-interactive app. The original bug was that hasattr() checks
# returned True for `ws_handler = None`, causing AttributeError.
# ---------------------------------------------------------------------------


class TestDevServerGuards:
    def test_non_interactive_app_has_none_handlers(self):
        app = _make_non_interactive_app()
        try:
            assert app.ws_handler is None
            assert app.http_handler is None
            assert app.web_transport_handler is None
        finally:
            shutil.rmtree(app._test_dir, ignore_errors=True)

    def test_is_not_none_guard_skips_none_handlers(self):
        """Regression test: the fixed guards must correctly skip when
        handlers are None in non-interactive mode. The old `hasattr()`
        guards would have tried to call .broadcast_reload() on None.
        """
        app = _make_non_interactive_app()
        try:
            # Reproduce the guarded block from dev_server.py
            for handler_name in ("ws_handler", "http_handler", "web_transport_handler"):
                handler = getattr(app, handler_name, None)
                # The fixed guard — must evaluate False for None.
                assert (handler is not None) is False
        finally:
            shutil.rmtree(app._test_dir, ignore_errors=True)

    def test_interactive_app_has_handlers(self):
        """Regression guard — interactive mode must still have handlers
        so the existing hot reload path is preserved.
        """
        scaffold = _make_non_interactive_app()
        try:
            app = PyWire(
                pages_dir=str(scaffold.pages_dir),
                interactive_server_mode=True,
            )
            assert app.ws_handler is not None
            assert app.http_handler is not None
            assert app.web_transport_handler is not None
        finally:
            shutil.rmtree(scaffold._test_dir, ignore_errors=True)
