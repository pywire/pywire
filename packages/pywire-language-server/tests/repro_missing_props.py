
import asyncio
import sys
import os
from unittest.mock import MagicMock
from lsprotocol.types import (
    CompletionParams, Position, TextDocumentIdentifier, 
    CompletionContext, CompletionTriggerKind
)
import logging

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

from pywire_language_server.server import (
    completions, documents, PyWireDocument, server
)

# Configure logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

import pywire_language_server.server as server_mod
print(f"DEBUG: server module file: {server_mod.__file__}")

async def run_test():
    print("--- Setting up Mock Environment ---")
    
    import tempfile
    import shutil
    
    tmp_dir = tempfile.mkdtemp()
    try:
        # Create a file-based component (no class named 'Form')
        # This matches form.wire structure
        comp_dir = os.path.join(tmp_dir, "components")
        os.makedirs(comp_dir)
        with open(os.path.join(comp_dir, "form.wire"), "w") as f:
            f.write("""---
from pywire import props

@props
class Props:
    on_submit: callable
    model: any
---
<form>
    <slot />
</form>
""")

        # Mock document content importing Form
        doc_path = os.path.join(tmp_dir, "test.wire")
        doc_uri = f"file://{doc_path}"
        doc_content = """
---
from .components.form import Form
---
<div>
    <Form 
</div>
"""
        # Register document
        doc = PyWireDocument(doc_uri, doc_content)
        documents[doc_uri] = doc
        
        # Mock LS
        ls = MagicMock()
        
        print("\n--- Triggering Prop Completion for <Form ---")
        # Line 5 is "    <Form "
        # 0123456789
        # Cursor at 10 (valid space after Form)
        # 0: empty, 1:---, 2:import, 3:---, 4:div, 5: <Form
        pos = Position(line=5, character=10)
        params = CompletionParams(
            text_document=TextDocumentIdentifier(uri=doc_uri),
            position=pos
        )
        
        res = await completions(ls, params)
        if len(res.items) > 0:
            print("Inspection of items:")
            for item in res.items:
                print(f" - Label: {item.label}, Kind: {item.kind}, SortText: {item.sort_text}")
        
        prop_labels = [item.label for item in res.items if item.kind == 10] # 10 is Property
        print(f"Prop Labels: {prop_labels}")
        
        found_props = "on_submit" in prop_labels and "model" in prop_labels
        
        # Check sort order: props should have sortText starting with '0'
        sorted_correctly = True
        for item in res.items:
            if item.kind == 10 and not item.sort_text.startswith("0"):
                print(f"FAILURE: Prop {item.label} has wrong sortText: {item.sort_text}")
                sorted_correctly = False
            elif item.kind != 10 and item.sort_text and not item.sort_text.startswith("1"):
                 # Assuming framework items adhere to '1' prefix
                 print(f"FAILURE: Non-prop {item.label} has wrong sortText: {item.sort_text}")
                 sorted_correctly = False

        if found_props and sorted_correctly:
            print("SUCCESS: Found props for file-based component and sort order is correct.")
        else:
            print("FAILURE: Issues detected.")
            
    except Exception as e:
        print(f"CRASHED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    asyncio.run(run_test())
