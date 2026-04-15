"""Tests for hot reload handler name evolution and race condition fix.

Verifies that:
1. Inline expressions produce _handler_N wrappers
2. Named function handlers use the function name directly
3. The two are incompatible (old handler name not on new class)
4. broadcast_reload defers connection_pages update until after send
"""

import ast
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


# -- Compilation tests --


class TestHandlerNameEvolution(unittest.TestCase):
    """Verify handler name changes when going from inline expr to named function."""

    def setUp(self) -> None:
        self.generator = CodeGenerator()
        self.parser = PyWireParser()

    def _compile(self, wire_content: str) -> str:
        parsed = self.parser.parse(wire_content)
        module_ast = self.generator.generate(parsed)
        return ast.unparse(module_ast)

    def test_inline_expression_produces_handler_wrapper(self) -> None:
        """@click={count.value += 1} should generate _handler_0."""
        content = "---\ncount = wire(0)\n---\n<button @click={count.value += 1}>Inc</button>"
        code = self._compile(content)

        self.assertIn("_handler_0", code)
        self.assertIn("data-on-click", code)

    def test_named_function_uses_direct_name(self) -> None:
        """@click={increment} where increment is defined should NOT generate _handler_0."""
        content = (
            "---\n"
            "count = wire(0)\n"
            "\n"
            "def increment():\n"
            "    count.value += 1\n"
            "---\n"
            "<button @click={increment}>Inc</button>"
        )
        code = self._compile(content)

        # Should use 'increment' directly, not a _handler_N wrapper
        self.assertNotIn("_handler_0", code)
        self.assertIn("def increment(self)", code)
        self.assertIn("data-on-click", code)
        # The template should reference 'increment' as the handler
        self.assertIn("'increment'", code)

    def test_handler_name_incompatibility(self) -> None:
        """Old handler name _handler_0 should not exist on the new class."""
        new_content = (
            "---\n"
            "count = wire(0)\n"
            "\n"
            "def increment():\n"
            "    count.value += 1\n"
            "---\n"
            "<button @click={increment}>Inc</button>"
        )
        parsed = self.parser.parse(new_content)
        module_ast = self.generator.generate(parsed)
        code_obj = compile(module_ast, "<test>", "exec")
        ns: dict = {}

        # Provide required runtime imports
        from pywire.runtime.page import BasePage

        ns["BasePage"] = BasePage
        ns["__page_class__"] = None

        exec(code_obj, ns)

        page_class = ns.get("__page_class__") or next(
            v
            for v in ns.values()
            if isinstance(v, type) and issubclass(v, BasePage) and v is not BasePage
        )

        # The new class should have 'increment' but NOT '_handler_0'
        self.assertTrue(hasattr(page_class, "increment"))
        self.assertFalse(hasattr(page_class, "_handler_0"))


# -- broadcast_reload ordering tests --


class _FakePage:
    """Minimal fake page for broadcast_reload tests (avoids MagicMock __dict__ issues)."""

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        self._components: dict = {}  # type: ignore[type-arg]
        self._component_state_snapshots: dict = {}  # type: ignore[type-arg]
        self._on_update = None
        self.user = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestBroadcastReloadOrdering(unittest.TestCase):
    """Verify connection_pages is updated only after send."""

    def test_connection_pages_updated_after_send(self) -> None:
        """connection_pages should point to new page only after send_bytes."""
        from pywire.runtime.websocket import WebSocketHandler

        handler = WebSocketHandler.__new__(WebSocketHandler)
        handler.active_connections = set()
        handler.connection_pages = {}
        handler.session_ids = {}

        # Mock connection
        mock_ws = AsyncMock()
        send_order: list[str] = []

        old_page = _FakePage()
        old_page.request = MagicMock()
        old_page.request.url.path = "/"
        old_page.params = {}
        old_page.query = {}
        old_page.path = {}
        old_page.url = None

        async def track_send(data: bytes) -> None:
            send_order.append(
                "old" if handler.connection_pages.get(mock_ws) is old_page else "new"
            )

        mock_ws.send_bytes = track_send
        handler.active_connections.add(mock_ws)
        handler.connection_pages[mock_ws] = old_page

        # New page whose render succeeds
        new_page = _FakePage()
        mock_render_response = MagicMock()
        mock_render_response.body = b"<div>updated</div>"
        new_page.render = AsyncMock(return_value=mock_render_response)  # type: ignore[attr-defined]

        new_page_class = MagicMock(return_value=new_page)

        mock_app = MagicMock()
        mock_app.router.match.return_value = (new_page_class, {}, None)
        handler.app = mock_app

        asyncio.get_event_loop().run_until_complete(handler.broadcast_reload())

        # send_bytes should have been called while old page was still active
        self.assertEqual(send_order, ["old"])
        # After broadcast_reload, connection_pages should have new page
        self.assertIs(handler.connection_pages[mock_ws], new_page)

    def test_render_failure_keeps_old_page(self) -> None:
        """If render fails, connection_pages should retain old page."""
        from pywire.runtime.websocket import WebSocketHandler

        handler = WebSocketHandler.__new__(WebSocketHandler)
        handler.active_connections = set()
        handler.connection_pages = {}
        handler.session_ids = {}

        mock_ws = AsyncMock()
        handler.active_connections.add(mock_ws)

        old_page = _FakePage()
        old_page.request = MagicMock()
        old_page.request.url.path = "/"
        old_page.params = {}
        old_page.query = {}
        old_page.path = {}
        old_page.url = None

        handler.connection_pages[mock_ws] = old_page

        # New page whose render raises
        new_page = _FakePage()
        new_page.render = AsyncMock(side_effect=RuntimeError("render failed"))  # type: ignore[attr-defined]

        new_page_class = MagicMock(return_value=new_page)

        mock_app = MagicMock()
        mock_app.router.match.return_value = (new_page_class, {}, None)
        handler.app = mock_app

        asyncio.get_event_loop().run_until_complete(handler.broadcast_reload())

        # Old page should be restored after failure
        self.assertIs(handler.connection_pages[mock_ws], old_page)
        # Hard reload message should have been sent
        mock_ws.send_bytes.assert_called()


if __name__ == "__main__":
    unittest.main()
