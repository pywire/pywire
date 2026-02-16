
import asyncio
import sys
import os
from unittest.mock import MagicMock
from lsprotocol.types import (
    CompletionParams, Position, TextDocumentIdentifier, 
    CompletionContext, CompletionTriggerKind, DefinitionParams
)

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

from pywire_language_server.server import (
    completions, definition, documents, PyWireDocument, 
    _is_inside_opening_tag
)
import logging
logging.basicConfig(level=logging.DEBUG)

async def run_test():
    print("--- Setting up Mock Environment ---")
    
    # Create temp directory for clean testing
    import tempfile
    import shutil
    
    tmp_dir = tempfile.mkdtemp()
    try:
        # Create component file
        comp_dir = os.path.join(tmp_dir, "components")
        os.makedirs(comp_dir)
        comp_file = os.path.join(comp_dir, "my_component.py")
        
        with open(comp_file, "w") as f:
            f.write("""
from pywire import component, html

@component
class MyComponent:
    class Props:
        existing: str
        my_prop: int
        is_valid: bool
        
    def render(self):
        return html.div()
""")
        
        # Create constants file to test filtering non-components
        const_file = os.path.join(tmp_dir, "constants.py")
        with open(const_file, "w") as f:
            f.write("SIZE = 100\n")
            
        # Mock document content
        doc_path = os.path.join(tmp_dir, "test.wire")
        doc_uri = f"file://{doc_path}"
        doc_content = """
---
import bs4
from .components.my_component import MyComponent
from .constants import SIZE

@component
class TestPage:
    def handler(self):
        pass

---
<div>
    <!-- Test 1: Component completion -->
    <
    
    <!-- Test 2: Prop completion -->
    <MyComponent 
    
    <MyComponent existing="val" >
    
</div>
"""
        doc = PyWireDocument(doc_uri, doc_content)
        documents[doc_uri] = doc
        
        # Mock LS
        ls = MagicMock()
        
        print(f"Test Root: {tmp_dir}")
        
        print("\n--- Test 1: Component Completion (< trigger) ---")
        # Position after '<' on line 14 (0-indexed)
        # Line 14 is "    <"
        pos_comp = Position(line=14, character=5) 
        params_comp = CompletionParams(
            text_document=TextDocumentIdentifier(uri=doc_uri),
            position=pos_comp,
            context=CompletionContext(trigger_kind=CompletionTriggerKind.TriggerCharacter, trigger_character="<")
        )
        
        res_comp = await completions(ls, params_comp)
        print(f"Items found: {len(res_comp.items)}")
        
        labels = [item.label for item in res_comp.items]
        print(f"Labels: {labels}")
        
        # Assertion for unwanted items (implicit imports)
        if "Any" in labels:
            print("FAILURE: Found 'Any' (implicit import) in completions!")
        if "EventData" in labels:
             print("FAILURE: Found 'EventData' (implicit import) in completions!")
             
        if "SIZE" in labels:
             print("FAILURE: Found 'SIZE' (non-component explicit import) in completions!")
             
        # Check strictness
        if "MyComponent" in labels and "Any" not in labels and "SIZE" not in labels:
            print("SUCCESS: Only user imports found.")

        print("\n--- Test 2: Prop Completion (inside tag) ---")
        # Position inside <MyComponent on line 17
        # Line 17 is "    <MyComponent "
        pos_prop = Position(line=17, character=17)
        params_prop = CompletionParams(
            text_document=TextDocumentIdentifier(uri=doc_uri),
            position=pos_prop
        )
        
        res_prop = await completions(ls, params_prop)
        print(f"Items found: {len(res_prop.items)}")
        # Print valid items
        for item in res_prop.items:
            print(f" - {item.label} ({item.kind})")
            
        print("\n--- Test 3: Go to Definition (Prop) ---")
        # Line 19: <MyComponent existing="val" >
        pos_def = Position(line=19, character=18)
        params_def = DefinitionParams(
            text_document=TextDocumentIdentifier(uri=doc_uri),
            position=pos_def
        )
        
        res_def = await definition(ls, params_def)
        print(f"Definition Result: {res_def}")
        if res_def:
             if isinstance(res_def, list):
                 for loc in res_def:
                     print(f" - URI: {loc.uri}")
                     print(f" - Range: {loc.range.start.line}:{loc.range.start.character}")
             else:
                 print(f" - URI: {res_def.uri}")
                 print(f" - Range: {res_def.range.start.line}:{res_def.range.start.character}")

    finally:
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    asyncio.run(run_test())
