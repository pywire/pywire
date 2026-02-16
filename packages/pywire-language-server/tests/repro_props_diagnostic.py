
import sys
import os
import asyncio
from unittest.mock import MagicMock

# Mock dependencies
for mod in ["starlette", "starlette.applications", "starlette.responses", "starlette.requests", "uvicorn", "watchfiles", "jinja2", "textual", "rich_click", "pydantic"]:
    sys.modules[mod] = MagicMock()

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from lsprotocol.types import (
    Diagnostic,
    Position,
    Range
)
from pywire_language_server.server import validate, server as ls_instance, documents

# Mock Document
class MockDocument:
    def __init__(self, uri, source):
        self.uri = uri
        self.text = source
        self.lines = source.splitlines()
        self.diagnostics = []
        self.directive_ranges = {"path": (0, 0)} # Minimal

    def get_python_source(self):
        parts = self.text.split("---")
        if len(parts) >= 3:
            return parts[1]
        return ""

def test_props_diagnostic():
    # Setup
    uri = "file:///tmp/test.wire"
    CONTENT = """---
from pywire import props

@props
class PropsA:
    a: int

@props
class PropsB:
    b: int
---
<div></div>
"""
    doc = MockDocument(uri, CONTENT)
    documents[uri] = doc
    
    # Mock ls.text_document_publish_diagnostics
    ls_instance.text_document_publish_diagnostics = MagicMock()
    
    print("Running validate...")
    validate(ls_instance, uri)
    
    # Check if diagnostics were published
    published = ls_instance.text_document_publish_diagnostics.call_args
    if published:
        params = published[0][0]
        print(f"Published diagnostics: {len(params.diagnostics)}")
        for d in params.diagnostics:
            print(f" - {d.message} at line {d.range.start.line}")
            
        has_error = any("Multiple @props" in d.message for d in params.diagnostics)
        if has_error:
            print("SUCCESS: Multiple @props diagnostic found")
        else:
            print("FAIL: Multiple @props diagnostic NOT found")
    else:
        print("FAIL: No diagnostics published at all")

if __name__ == "__main__":
    test_props_diagnostic()
