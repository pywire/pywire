import ast
import unittest
from unittest.mock import MagicMock, AsyncMock
from pywire.runtime.page import BasePage
from pywire.runtime.events import EventData
from pywire.compiler.parser import PyWireParser
from pywire.compiler.codegen.generator import CodeGenerator

class TestMinorFeaturesV0111(unittest.TestCase):
    def setUp(self):
        self.parser = PyWireParser()
        self.generator = CodeGenerator()

    def test_navigate_sets_pending_navigation(self):
        """Verify that calling navigate() sets the _pending_navigation flag."""
        # Mock request, params, query
        page = BasePage(MagicMock(), {}, {})
        
        # Test the navigate property
        navigator = page.navigate
        navigator("/new/path")
        
        self.assertEqual(page._pending_navigation, "/new/path")

    def test_custom_event_codegen(self):
        """Verify that @custom-event generates correct handler mapping."""
        from textwrap import dedent
        source = dedent("""
        ---
        async def on_custom(event):
            pass
        ---
        <div @my-custom-event={on_custom}></div>
        """)
        parsed = self.parser.parse(source)
        module_ast = self.generator.generate(parsed)
        code = ast.unparse(module_ast)
        
        # Should generate a data-on-my-custom-event attribute
        self.assertIn("data-on-my-custom-event", code)
        # Should reference the handler
        self.assertIn("on_custom", code)

    def test_event_data_structure(self):
        """Verify EventData handles snake_case and dot access."""
        data = EventData({"client_x": 100, "key": "Enter"})
        
        # Direct access
        self.assertEqual(data.client_x, 100)
        
        # Case conversion (camelCase key from client -> snake_case access?)
        # Actually EventData as implemented supports: 
        # python attr "camel" -> dict key "camel"
        # The implementation in page.py:
        # camel = re.sub(r"(?!^)_([a-z])", lambda x: x.group(1).upper(), name)
        # So data.clientX should access data["clientX"]
        
        data_camel = EventData({"clientX": 200})
        self.assertEqual(data_camel.client_x, 200)
        self.assertEqual(data_camel.clientX, 200)

if __name__ == "__main__":
    unittest.main()
