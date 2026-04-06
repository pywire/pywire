
import unittest
import re
from typing import Any
from pywire.core.wire import wire
from pywire.compiler.parser import PyWireParser
from pywire.runtime.router import Router
from pywire.runtime.page import BasePage

class TestReproduction(unittest.TestCase):
    def test_wire_interpolation(self):
        print("\n--- Test Wire Interpolation ---")
        count = wire(1)
        result = f"{count}"
        print(f"f'{count}' -> '{result}'")
        
        # Current failure: returns wire(1)
        # We want "1"
        if result == "1":
            print("PASS: Wire interpolation unwrapped")
        else:
            print("FAIL: Wire interpolation NOT unwrapped")

    def test_whitespace_stripping(self):
        print("\n--- Test Whitespace Stripping ---")
        from pywire.compiler.parser import PyWireParser
        from pywire.compiler.codegen.generator import CodeGenerator
        import ast
        
        parser = PyWireParser()
        generator = CodeGenerator()
        content = "<p>Clicked {count} times</p>"
        
        # Compile and instantiate
        try:
            parsed = parser.parse(content, "test.wire")
            module_ast = generator.generate(parsed)
            # Fix: module_ast is an ast.Module. We need to set its lineno etc if not set.
            # Generator usually handles this.
            
            code = compile(module_ast, "test.wire", "exec")
            
            # Run the code to get the page class
            ns = {
                "wire": wire,
            }
            # We need some helper functions that the generated code might call
            from pywire.runtime.loader import load_component
            from pywire.runtime.helpers import render_attrs
            from pywire.runtime.escape import escape_html
            ns["load_component"] = load_component
            ns["render_attrs"] = render_attrs
            ns["escape_html"] = escape_html
            
            exec(code, ns)
            # Find the class that inherits from BasePage
            from pywire.runtime.page import BasePage
            PageClass = None
            for v in ns.values():
                if isinstance(v, type) and issubclass(v, BasePage) and v is not BasePage:
                    PageClass = v
                    break
            
            if not PageClass:
                print(f"FAIL: No Page class found in generated code. Keys: {list(ns.keys())}")
                return
            
            # Instantiate and render
            from unittest.mock import MagicMock
            mock_request = MagicMock()
            page = PageClass(request=mock_request, params={}, query={})
            page.count = wire(1)
            # Mock some context for _render_template
            page._context = {}
            page._background_tasks = set()
            
            import asyncio
            result = asyncio.run(page._render_template())
            print(f"Rendered: '{result}'")
            
            if "Clicked 1 times" in result:
                print("PASS: Whitespace preserved")
            else:
                print(f"FAIL: Whitespace NOT preserved (got '{result}')")
                
        except Exception as e:
            print(f"Compilation/Rendering error: {e}")
            import traceback
            traceback.print_exc()

    def test_router_param_types(self):
        print("\n--- Test Router Param Types ---")
        router = Router()
        class MockPage(BasePage): pass
        
        router.add_route("/test/:id:int", MockPage)
        
        match = router.match("/test/123")
        if match:
            _, params, _ = match
            print(f"Params: {params}")
            if isinstance(params["id"], int):
                print("PASS: Param is int")
            else:
                print(f"FAIL: Param is {type(params['id'])} (expected int)")
        else:
            print("FAIL: No match found")

if __name__ == "__main__":
    unittest.main()
