
import sys
import os
import asyncio
from unittest.mock import MagicMock
# Mock heavy dependencies
for mod in ["starlette", "starlette.applications", "starlette.responses", "starlette.requests", "uvicorn", "watchfiles", "jinja2", "textual", "rich_click", "pydantic"]:
    m = MagicMock()
    sys.modules[mod] = m
    # To handle 'from starlette.requests import Request'
    if "." in mod:
        parent, child = mod.rsplit(".", 1)
        if parent in sys.modules:
            setattr(sys.modules[parent], child, m)

from pywire_language_server import server as server_mod
print(f"DEBUG: server module file: {server_mod.__file__}")
from pywire_language_server.server import completions, _extract_props_from_file

# Create a mock file with multiple @props classes
TEST_FILE = "/tmp/test_component_multiple_props.wire"
TEST_CONTENT = """
---
from pywire import component, props

@component
class MyComponent:
    pass

@props
class Props1:
    prop1: str

@props
class Props2:
    prop2: int
---

<div></div>
"""

with open(TEST_FILE, "w") as f:
    f.write(TEST_CONTENT)

def test_extract_props():
    print(f"--- Extracting props from {TEST_FILE} ---")
    props = _extract_props_from_file("file://" + TEST_FILE, "MyComponent")
    print(f"Found props: {[p.name for p in props]}")
    
    # Assert behavior: Currently it might pick one or none depending on logic
    # The requirement is to error, but for now we just see what happens.
    
def test_compiler_error_logic():
    print("\n--- Testing Compiler Enforcement Logic ---")
    import ast
    # We can't easily run the real generator without full environment,
    # but we can verify the same logic I added to it.
    
    # Simulate _extract_props_from_ast logic:
    tree = ast.parse(TEST_CONTENT.split("---")[1])
    props_classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and any(d.id == "props" for d in n.decorator_list if isinstance(d, ast.Name))]
    
    if len(props_classes) > 1:
        print(f"SUCCESS: Logic detected {len(props_classes)} @props classes (would raise error)")
    else:
        print(f"FAIL: Logic failed to detect multiple @props classes")

if __name__ == "__main__":
    test_extract_props()
    test_compiler_error_logic()
