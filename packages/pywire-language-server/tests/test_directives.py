
import pytest
import os
from unittest.mock import Mock
from pathlib import Path
from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    DidOpenTextDocumentParams,
    TextDocumentItem,
    Position,
    TextDocumentIdentifier,
    CompletionParams,
    DefinitionParams,
    Diagnostic,
    DiagnosticSeverity
)
from pywire_language_server.server import (
    validate,
    completions,
    definition,
    documents,
    PyWireDocument,
)

@pytest.fixture
def mock_ls():
    ls = Mock(spec=LanguageServer)
    return ls

@pytest.fixture
def clean_documents():
    documents.clear()
    yield
    documents.clear()

def test_validate_directives(mock_ls, clean_documents):
    uri = "file:///test.wire"
    
    test_cases = [
        ("!layout 'base.wire'", ["Layout file not found"]), 
        ("!layout base.wire", ["Layout path must be a string literal"]), 
        ("!layout 'base.py'", ["Layout file must have .wire extension"]),
        ("!path 'relative'", ["Path route must be absolute"]),
        ("!path '/:id:float'", ["Unsupported parameter type 'float'"]),
        ("!path '/:123'", ["Invalid parameter name '123'"]),
        ("!path '/:id:int'", []),
        ("!unknown", ["Unknown directive '!unknown'"]),
        ("!no_spa", []),
        ("!no_spa args", ["!no_spa directive does not accept arguments"]),
    ]

    for text, expected_msgs in test_cases:
        # Manually clear diagnostics and documents for each sub-case to be clean
        documents.clear()
        doc = PyWireDocument(uri, text)
        documents[uri] = doc
        
        # Capture diagnostics
        published_diagnostics = []
        def capture(params):
            published_diagnostics.extend(params.diagnostics)
        mock_ls.text_document_publish_diagnostics = capture
        
        validate(mock_ls, uri)
        
        messages = [d.message for d in published_diagnostics]
        
        if not expected_msgs:
            assert not messages, f"Expected no diagnostics for '{text}', got {messages}"
        else:
            for exp in expected_msgs:
                assert any(exp in m for m in messages), f"Expected '{exp}' in diagnostics for '{text}', got {messages}"

@pytest.mark.asyncio
async def test_completion_directives(mock_ls, clean_documents):
    uri = "file:///test.wire"
    
    # 1. Empty line (Header context)
    text1 = ""
    doc1 = PyWireDocument(uri, text1)
    documents[uri] = doc1
    
    res1 = await completions(mock_ls, CompletionParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=Position(line=0, character=0)
    ))
    labels1 = [item.label for item in res1.items]
    assert "!layout" in labels1
    assert "!path" in labels1

    # 2. '!' trigger
    text2 = "!"
    doc2 = PyWireDocument(uri, text2)
    documents[uri] = doc2
    
    res2 = await completions(mock_ls, CompletionParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=Position(line=0, character=1)
    ))
    labels2 = [item.label for item in res2.items]
    assert "!layout" in labels2

@pytest.mark.asyncio
async def test_completion_path_directives(mock_ls, clean_documents, tmp_path):
    # Test path completion inside !layout literal
    root = tmp_path
    main_file = root / "main.wire"
    layout_dir = root / "layouts"
    layout_dir.mkdir()
    (layout_dir / "base.wire").touch()
    (layout_dir / "other.wire").touch()
    (root / "shared.wire").touch()
    
    main_uri = f"file://{main_file}"
    
    # Test 1: Suggesing 'layouts/' when typing './'
    text1 = "!layout './'"
    doc1 = PyWireDocument(main_uri, text1)
    documents[main_uri] = doc1
    
    res1 = await completions(mock_ls, CompletionParams(
        text_document=TextDocumentIdentifier(uri=main_uri),
        position=Position(line=0, character=11) # inside literal after ./
    ))
    labels1 = [item.label for item in res1.items]
    assert "layouts/" in labels1
    assert "shared.wire" in labels1

    # Test 2: Suggesting files inside 'layouts/'
    text2 = "!layout './layouts/'"
    doc2 = PyWireDocument(main_uri, text2)
    documents[main_uri] = doc2
    
    res2 = await completions(mock_ls, CompletionParams(
        text_document=TextDocumentIdentifier(uri=main_uri),
        position=Position(line=0, character=19) # inside literal after layouts/
    ))
    labels2 = [item.label for item in res2.items]
    assert "base.wire" in labels2
    assert "other.wire" in labels2

@pytest.mark.asyncio
async def test_definition_directives(mock_ls, clean_documents, tmp_path):
    # Use tmp_path fixture for real file system simulation
    root = tmp_path
    main_file = root / "main.wire"
    layout_dir = root / "layouts"
    layout_dir.mkdir()
    layout_file = layout_dir / "base.wire"
    layout_file.touch()
    
    # We need to use real absolute paths because definition() resolve()s
    main_uri = Path(main_file).as_uri()
    text = "!layout 'layouts/base.wire'"
    doc = PyWireDocument(main_uri, text)
    documents[main_uri] = doc
    
    # Test clicking anywhere in the path string (e.g. index 12, 'l' in layouts)
    res_dir = await definition(mock_ls, DefinitionParams(
        text_document=TextDocumentIdentifier(uri=main_uri),
        position=Position(line=0, character=12)
    ))
    
    assert res_dir is not None
    assert len(res_dir) == 1
    # Should resolve to the FILE base.wire, not the 'layouts' directory anymore
    assert res_dir[0].uri.endswith("base.wire")

    # Test clicking on the filename part (e.g. index 20, 'b' in base.wire)
    res_file = await definition(mock_ls, DefinitionParams(
        text_document=TextDocumentIdentifier(uri=main_uri),
        position=Position(line=0, character=20)
    ))
    
    assert res_file is not None
    assert len(res_file) == 1
    assert res_file[0].uri.endswith("base.wire")
