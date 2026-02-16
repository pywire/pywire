
import sys
import os
import asyncio
from unittest.mock import MagicMock
from pathlib import Path
import builtins

# Mock dependencies
for mod in ["starlette", "starlette.applications", "starlette.responses", "starlette.requests", "uvicorn", "watchfiles", "jinja2", "textual", "rich_click", "pydantic"]:
    sys.modules[mod] = MagicMock()

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lsprotocol.types import (
    CompletionParams,
    TextDocumentIdentifier,
    Position,
    DefinitionParams
)
from pywire_language_server.server import completions, definition, server as ls_instance, documents

# Mock Document
class MockDocument:
    def __init__(self, uri, source):
        self.uri = uri
        self.text = source
        self.lines = source.splitlines()
        self.transpiler = MagicMock()
        self.source_map = MagicMock()
        self.source_map.to_generated.return_value = None
        self.source_map.to_original.side_effect = lambda l, c: (l, c)
        self.directive_ranges = {}

    def get_python_source(self):
        parts = self.text.split("---")
        if len(parts) >= 3:
            return parts[1]
        return ""
        
    def map_to_original(self, line, col):
        return line, col

    def map_to_generated(self, line, col):
        return None

def test_bugs():
    async def run_tests():
        # Setup documents global
        documents.clear()
        
        # 1. Test Component Go-to-Definition
        CONTENT_1 = """---
from .form import Form
---

<div>
    <Form />
</div>
"""
        doc1 = MockDocument("file:///tmp/test1.wire", CONTENT_1)
        documents["file:///tmp/test1.wire"] = doc1
        
        # line 0: ---
        # line 1: from .form import Form
        # line 2: ---
        # line 3: empty
        # line 4: <div>
        # line 5:     <Form />
        params1 = DefinitionParams(
            text_document=TextDocumentIdentifier(uri="file:///tmp/test1.wire"),
            position=Position(line=5, character=5)
        )
        
        # Mock filesystem for form.wire
        FORM_CONTENT = """---
from pywire import props
@props
class FormProps:
    model: str
---
<div></div>
"""
        orig_exists = os.path.exists
        orig_path_exists = Path.exists
        orig_open = builtins.open
        
        def mock_exists(p):
            if str(p).endswith("form.wire"): return True
            return orig_exists(p)
        def mock_path_exists(self):
            if str(self).endswith("form.wire"): return True
            return orig_path_exists(self)
        def mock_open(p, mode="r", *args, **kwargs):
            if str(p).endswith("form.wire"):
                m = MagicMock()
                m.__enter__.return_value.read.return_value = FORM_CONTENT
                return m
            return orig_open(p, mode, *args, **kwargs)
            
        os.path.exists = mock_exists
        Path.exists = mock_path_exists
        builtins.open = mock_open
        
        print("--- Bug 1: Component Definition ---")
        try:
            res1 = await definition(ls_instance, params1)
            if res1:
                print(f"SUCCESS: Definition found at {res1[0].uri}")
            else:
                print("FAIL: Definition NOT found for <Form>")
        except Exception as e:
            print(f"ERROR: {e}")

        # 2. Test InputElement completion
        CONTENT_2 = """---
from pywire.core.web_types import InputElement
from .my_comp import MyComp
---
<div><</div>
"""
        doc2 = MockDocument("file:///tmp/test2.wire", CONTENT_2)
        documents["file:///tmp/test2.wire"] = doc2
        
        # line 0: ---
        # line 1: from pywire.core.web_types import InputElement
        # line 2: from .my_comp import MyComp
        # line 3: ---
        # line 4: <div><</div>
        params2 = CompletionParams(
            text_document=TextDocumentIdentifier(uri="file:///tmp/test2.wire"),
            position=Position(line=4, character=6)
        )
        
        print("\n--- Bug 2: Filter InputElement ---")
        res2 = await completions(ls_instance, params2)
        labels2 = [i.label for i in res2.items]
        print(f"Completions: {labels2}")
        if "InputElement" in labels2:
            print("FAIL: InputElement should NOT be suggested")
        elif "MyComp" in labels2:
            print("SUCCESS: MyComp suggested, InputElement filtered")
        else:
            print("FAIL: No components suggested")

        # 3. Test Prop Definition mapping (off-by-one)
        CONTENT_3 = """---
from .form import Form
---
<Form model="" />
"""
        doc3 = MockDocument("file:///tmp/test3.wire", CONTENT_3)
        documents["file:///tmp/test3.wire"] = doc3
        
        # line 0: ---
        # line 1: from .form import Form
        # line 2: ---
        # line 3: <Form model="" />
        params3 = DefinitionParams(
            text_document=TextDocumentIdentifier(uri="file:///tmp/test3.wire"),
            position=Position(line=3, character=7)
        )
        
        print("\n--- Bug 3: Prop Mapping Offset ---")
        # In FORM_CONTENT:
        # line 0: ---
        # line 1: from pywire import props
        # line 2: @props
        # line 3: class FormProps:
        # line 4:     model: str
        # line 5: ---
        # So 'model' is on line 4 (0-indexed)
        
        res3 = await definition(ls_instance, params3)
        if res3:
            actual_line = res3[0].range.start.line
            print(f"Definition found at line: {actual_line}")
            if actual_line == 4:
                print("SUCCESS: Line 4 correctly identified")
            else:
                print(f"FAIL: Expected line 4, got {actual_line}")
        else:
            print("FAIL: Prop definition NOT found")

        # Restore mocks
        os.path.exists = orig_exists
        Path.exists = orig_path_exists
        builtins.open = orig_open

    asyncio.run(run_tests())

if __name__ == "__main__":
    test_bugs()
