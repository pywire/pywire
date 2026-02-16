
import pytest
from unittest.mock import Mock, MagicMock
from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    DidOpenTextDocumentParams,
    TextDocumentItem,
    PublishDiagnosticsParams,
)
from pywire_language_server.server import (
    did_open,
    documents,
    ty_client,
    ty_diagnostics,
    _publish_diagnostics,
)

# Mock TyClient behavior
@pytest.fixture
def mock_ty_client():
    client = Mock()
    client.set_diagnostics_callback = Mock()
    return client

@pytest.fixture
def mock_ls():
    ls = Mock(spec=LanguageServer)
    return ls

@pytest.fixture
def clean_documents():
    documents.clear()
    yield
    documents.clear()

@pytest.mark.asyncio
async def test_diagnostics_mapping_repro(mock_ls, clean_documents, monkeypatch):
    """
    Simulate Ty sending a diagnostic for a syntax error and verify it maps back correctly.
    """
    # 1. Setup Mock Ty Client
    mock_ty = Mock()
    callback_storage = []
    
    def set_callback(cb):
        callback_storage.append(cb)
    
    mock_ty.set_diagnostics_callback = set_callback
    
    # Patch the global ty_client in server.py
    monkeypatch.setattr("pywire_language_server.server.ty_client", mock_ty)
    
    # 2. Open a document with a syntax error in Python block
    uri = "file:///repro.wire"
    text = """
---
def foo()
    pass # Missing colon above
---
<div></div>
"""
    did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))
    
    # 3. Simulate Ty finding the error in the shadow file
    # we need to know WHERE the shadow file is.
    # But server.py uses shadow_manager which uses disk I/O.
    # For this test, we care about the MAPPING logic in handle_diagnostics (which is inside initialize)
    # BUT handle_diagnostics is defined as a closure in initialize().
    # Using monkeypatch on 'ty_client' after initialize() is tricky if we want to capture the closure.
    # However, ty_client.set_diagnostics_callback IS called in initialize().
    # So if we run initialize() with our mocked client...
    
    # Easier check: Test _map_diagnostic directly or hook into existing mechanisms?
    # Let's rely on server.py's implementation details exposed in the module or verify mapping logic.
    
    # Actually, let's look at how server.py sets up.
    # It sets globals.
    
    # Let's try to invoke the callback that was registered.
    # We need to trigger initialization to register the callback.
    # But initialization requires running the server...
    
    # Alternative: Test internal mapping function directly?
    from pywire_language_server.server import _map_diagnostic, ShadowFileManager
    
    doc = documents[uri]
    # The Python block starts at line 2.
    # "def foo()" is line 2.
    # In shadow file, it will likely be offset by imports.
    
    # Let's inspect the generated code to find where "def foo()" ends up.
    generated_code = doc.get_python_source()
    gen_lines = generated_code.splitlines()
    
    def_foo_line_idx = -1
    for i, line in enumerate(gen_lines):
        if "def foo()" in line:
            def_foo_line_idx = i
            break
            
    assert def_foo_line_idx != -1, "Could not find 'def foo()' in generated code"
    
    # Syntax error "expected ':'" usually points to end of line or specific char
    # "def foo()" is 9 chars.
    # Diagnostic range in GENERATED code:
    gen_diag = {
        "range": {
            "start": {"line": def_foo_line_idx, "character": 8}, # After ')'
            "end": {"line": def_foo_line_idx, "character": 9}
        },
        "message": "expected ':'",
        "severity": 1
    }
    
    # 4. Map it back
    mapped_diag = _map_diagnostic(gen_diag, doc.source_map)
    
    # 5. Assertions
    assert mapped_diag is not None, "Diagnostic was dropped / failed to map"
    # Original: line 2, "def foo()"
    # Should map to line 2
    assert mapped_diag.range.start.line == 2
    
    # 5b. Test LOOSE mapping (e.g. error at newline char which might not be mapped)
    # "def foo()" length is 9. Col 0-8. 
    # If Ty says error at col 9 (after the parens, essentially the newline or space)
    # Strictly, this is not mapped if we only map the text content.
    gen_diag_loose = {
        "range": {
            "start": {"line": def_foo_line_idx, "character": 9}, 
            "end": {"line": def_foo_line_idx, "character": 10}
        },
        "message": "expected ':' (loose)",
        "severity": 1
    }
    
    # This SHOULD fail with current logic if newline isn't mapped
    mapped_diag_loose = _map_diagnostic(gen_diag_loose, doc.source_map)
    # We expect this to be None currently, but we WANT it to be mapped.
    # So if it is None, we know strict mapping is the issue.
    if mapped_diag_loose is None:
        pytest.fail("Strict mapping dropped diagnostic at line end (col 9). Fuzzy mapping needed.")

    
    # Additional Check: Syntax Error in Docstring (User's Case)
    text_user_repro = """
---
def calc():
    \"\"\"Doc\"\"\"\"
    return 1
---
"""
    uri2 = "file:///user_repro.wire"
    did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri2, language_id="pywire", version=1, text=text_user_repro
        )
    ))
    doc2 = documents[uri2]
    gen_code2 = doc2.get_python_source()
    # Find "Doc" line
    doc_line_idx = -1
    for i, line in enumerate(gen_code2.splitlines()):
        if '"""Doc""""' in line:
             doc_line_idx = i
             break
    
    assert doc_line_idx != -1
    
    # Syntax error likely at the 4th quote?
    # Line content: '    """Doc""""' (indent + quotes)
    # len is 4 + 3 + 3 + 4 = 14?
    # Indices: 0-3 indent, 4-6 open, 7-9 content, 10-13 quotes?
    # Error at char 13?
    
    gen_diag2 = {
        "range": {
            "start": {"line": doc_line_idx, "character": 13},
            "end": {"line": doc_line_idx, "character": 14}
        },
        "message": "Syntax error",
        "severity": 1
    }
    
    mapped_diag2 = _map_diagnostic(gen_diag2, doc2.source_map)
    
    if mapped_diag2 is None:
        print(f"\\nFAILED to map docstring error at line {doc_line_idx} char 13")
        print("Mappings for this line:")
        for m in doc2.source_map.mappings:
            if m.generated_line == doc_line_idx:
                print(m)
        assert False, "Docstring diagnostic dropped"

# Add new test for URI parsing
def test_shadow_uri_parsing():
    from pywire_language_server.server import ShadowFileManager
    
    # Needs absolute path for root
    sm = ShadowFileManager("/root")
    # Manually setup pywire_dir
    sm.pywire_dir = "/root/.pywire"
    sm.root_path = "/root"
    
    # Case A: proper file:// URI
    shadow_uri_a = "file:///root/.pywire/test.wire.py"
    orig_a = sm.get_original_uri(shadow_uri_a)
    assert orig_a == "file:///root/test.wire"
    
    # Case B: path only (no scheme) - THIS IS WHAT WE SUSPECT FAILS
    shadow_uri_b = "/root/.pywire/test.wire.py"
    orig_b = sm.get_original_uri(shadow_uri_b)
    
    if orig_b is None:
        pytest.fail("ShadowFileManager failed to resolve URI without file:// scheme. This is likely the bug.")
    assert orig_b == "file:///root/test.wire"

