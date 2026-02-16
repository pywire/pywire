
import sys
import os
from unittest.mock import MagicMock

# Mock dependencies
for mod in ["starlette", "starlette.applications", "starlette.responses", "starlette.requests", "uvicorn", "watchfiles", "jinja2", "textual", "rich_click", "pydantic"]:
    m = MagicMock()
    sys.modules[mod] = m
    if "." in mod:
        parent, child = mod.rsplit(".", 1)
        if parent in sys.modules:
            setattr(sys.modules[parent], child, m)

from lsprotocol.types import (
    CompletionParams,
    TextDocumentIdentifier,
    Position,
    CompletionItemKind
)

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from pywire_language_server import server as server_mod
# default_server is just 'server' in the module
default_server = server_mod.server
from pywire_language_server.server import completions

# Mock Document
class MockDocument:
    def __init__(self, uri, source):
        self.uri = uri
        self.source = source
        self.lines = source.splitlines()

    def get_python_source(self):
        parts = self.source.split("---")
        if len(parts) >= 3:
            return parts[1]
        return ""
        
    def map_to_generated(self, line, col):
        return None # Simplified: say it's not in python block
        
    @property
    def source_map(self):
        m = MagicMock()
        m.nearest_generated_on_line.return_value = None
        return m

    def map_to_original(self, line, col):
        return line, col # Simplified for test

# 1. Test Component Completion <_>
TEST_CONTENT_1 = """
---
from pywire import component
from .my_component import MyComponent
---

<div>
    <
</div>
"""
# Cursor after <
LINE_1 = 7
CHAR_1 = 5

# 2. Test Prop Completion <Form _>
TEST_CONTENT_2 = """
---
from .form import Form
---

<div>
    <Form >
</div>
"""
# Cursor after <Form_
LINE_2 = 6
CHAR_2 = 10

import asyncio

def test_regressions():
    async def run_tests():
        server = default_server
        # server.workspace = MagicMock()
        # We can't set server.workspace easily, but completions uses 'documents' global
        from pywire_language_server import server as server_module
        server_module.documents = {}

        print("--- Test 1: Component Completion <_> ---")
        doc1 = MockDocument("file:///tmp/test1.wire", TEST_CONTENT_1)
        # server.workspace.get_document.return_value = doc1 # Not used by completions directly
        server_module.documents["file:///tmp/test1.wire"] = doc1
        
        params1 = CompletionParams(
            text_document=TextDocumentIdentifier(uri="file:///tmp/test1.wire"),
            position=Position(line=LINE_1, character=CHAR_1)
        )
        
        res1 = await completions(server, params1)
        labels1 = [i.label for i in res1.items]
        print(f"Items found: {labels1}")
        if "MyComponent" in labels1:
            print("SUCCESS: MyComponent found")
        else:
            print("FAIL: MyComponent NOT found")

        print("\n--- Test 2: Prop Completion <Form _> ---")
        # Define mock form.wire content
        FORM_WIRE_CONTENT = """
---
from pywire import props

@props
class FormProps:
    framework: str
    action: str
---

<form>
    <slot />
</form>
"""
        
        # We need to mock filesystem check for form.wire
        import os
        from pathlib import Path
        original_exists = os.path.exists
        original_path_exists = Path.exists
        
        def mock_exists(path):
            if str(path).endswith("/tmp/form.wire"): return True
            return original_exists(path) if isinstance(path, (str, bytes)) else original_path_exists(path)
            
        def mock_path_exists(self):
            if str(self).endswith("/tmp/form.wire"): return True
            return original_path_exists(self)

        os.path.exists = mock_exists
        Path.exists = mock_path_exists

        # Mock open
        import builtins
        original_open = builtins.open
        def mock_open(path, mode="r", *args, **kwargs):
            if str(path).endswith("/tmp/form.wire"):
                m = MagicMock()
                m.__enter__.return_value.read.return_value = FORM_WIRE_CONTENT
                return m
            return original_open(path, mode, *args, **kwargs)
        builtins.open = mock_open

        doc2 = MockDocument("file:///tmp/test2.wire", TEST_CONTENT_2)
        server_module.documents["file:///tmp/test2.wire"] = doc2
        
        params2 = CompletionParams(
            text_document=TextDocumentIdentifier(uri="file:///tmp/test2.wire"),
            position=Position(line=LINE_2, character=CHAR_2)
        )
        
        res2 = await completions(server, params2)
        labels2 = [i.label for i in res2.items]
        print(f"Items found: {labels2}")
        
        # Restore mocks
        os.path.exists = original_exists
        Path.exists = original_path_exists
        builtins.open = original_open

        if "framework" in labels2 and "action" in labels2:
             print("SUCCESS: Prop suggestions found")
        else:
             print("FAIL: Prop suggestions NOT found")

    asyncio.run(run_tests())

if __name__ == "__main__":
    test_regressions()
