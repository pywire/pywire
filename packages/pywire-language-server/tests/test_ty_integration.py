
import pytest
from unittest.mock import Mock, AsyncMock
from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    CompletionParams,
    TextDocumentIdentifier,
    Position,
    DidOpenTextDocumentParams,
    TextDocumentItem,
    HoverParams,
    MarkupContent,
    DefinitionParams,
    ReferenceParams,
)
import pywire_language_server.server as server_module

@pytest.fixture
def mock_ls():
    return Mock(spec=LanguageServer)

@pytest.fixture
def mock_ty_client():
    client = Mock()
    client.send_request = AsyncMock()
    return client

@pytest.fixture(autouse=True)
def clean_globals():
    server_module.documents.clear()
    original_ty = server_module.ty_client
    original_shadow = server_module.virtual_manager
    yield
    server_module.documents.clear()
    server_module.ty_client = original_ty
    server_module.virtual_manager = original_shadow

@pytest.mark.asyncio
async def test_completion_trigger_kind(mock_ls, mock_ty_client):
    # Setup global state
    server_module.ty_client = mock_ty_client
    server_module.virtual_manager = Mock()
    server_module.virtual_manager.get_shadow_uri.return_value = "file:///shadow.py"
    
    # Mock document mapping
    uri = "file:///test.wire"
    text = """
---
x = 1
---
"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))
    
    # Trigger completion
    params = CompletionParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=Position(line=2, character=1),
        context=None 
    )
    
    await server_module.completions(mock_ls, params)
    
    # Verify triggerKind was added
    call_args = mock_ty_client.send_request.call_args
    assert call_args is not None
    method, req_params = call_args[0]
    assert method == "textDocument/completion"
    assert "context" in req_params
    assert req_params["context"]["triggerKind"] == 1


@pytest.mark.asyncio
async def test_hover_formatting(mock_ls, mock_ty_client):
    # Setup global state
    server_module.ty_client = mock_ty_client
    server_module.virtual_manager = Mock()
    server_module.virtual_manager.get_shadow_uri.return_value = "file:///shadow.py"

    uri = "file:///test.wire"
    text = """
---
x = 1
---
"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))

    # Mock Ty response - plaintext signature
    mock_ty_client.send_request.return_value = {
        "contents": {
            "kind": "plaintext",
            "value": "(function) def foo() -> int"
        }
    }

    params = HoverParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=Position(line=2, character=1),
    )

    result = await server_module.hover(mock_ls, params)


    assert result is not None
    assert isinstance(result.contents, MarkupContent)
    assert result.contents.kind == "markdown"
    assert "```python" in result.contents.value
    assert "(function) def foo() -> int" in result.contents.value

@pytest.mark.asyncio
async def test_hover_docstring_separation(mock_ls, mock_ty_client):
    # Setup global state
    server_module.ty_client = mock_ty_client
    server_module.virtual_manager = Mock()
    server_module.virtual_manager.get_shadow_uri.return_value = "file:///shadow.py"

    # Test that we separate signature from docstring
    uri = "file:///test.wire"
    text = """
---
def calc_total(): pass
---
"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))
    
    # Mock Ty response with signature + docstring + dashes
    mock_response = {
        "contents": {
            "kind": "plaintext",
            "value": "def calc_total() -> int\n-----------------\nCalculate total."
        }
    }
    
    async def mock_send_request(method, params):
        if method == "textDocument/hover":
            return mock_response
        return None

    mock_ty_client.send_request.side_effect = mock_send_request

    # Hover on 'calc_total'
    pos = Position(line=2, character=4)
    result = await server_module.hover(mock_ls, HoverParams(
        text_document=TextDocumentIdentifier(uri=uri), position=pos
    ))

    assert result is not None
    assert isinstance(result.contents, MarkupContent)
    val = result.contents.value
    
    # Signature should be wrapped
    assert "```python\ndef calc_total() -> int\n```" in val
    
    # Docstring should NOT be wrapped in python block
    # But should be present
    assert "Calculate total." in val
    
    # Dashes should be removed or handled
    assert "-----------------" not in val
    
    # Separator check
    assert "\n\n---\n\n" in val

@pytest.mark.asyncio
async def test_script_style_isolation(mock_ls):
    # Test that we ignore script/style tags
    uri = "file:///test.wire"
    text = """
<script>
  console.log("Hello");
</script>
<style>
  .foo { color: red; }
</style>
"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))

    # Inside script
    pos_script = Position(line=2, character=10)
    hover_res = await server_module.hover(mock_ls, HoverParams(
        text_document=TextDocumentIdentifier(uri=uri), position=pos_script
    ))
    assert hover_res is None

    comp_res = await server_module.completions(mock_ls, CompletionParams(
        text_document=TextDocumentIdentifier(uri=uri), position=pos_script, context=None
    ))
    assert comp_res.items == []

    # Inside style
    pos_style = Position(line=5, character=10)
    hover_res = await server_module.hover(mock_ls, HoverParams(
        text_document=TextDocumentIdentifier(uri=uri), position=pos_style
    ))
    assert hover_res is None


@pytest.mark.asyncio
async def test_shorthand_removal(mock_ls):
    uri = "file:///test.wire"
    text = """<div $foo></div>"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))

    # Hover on $foo
    pos = Position(line=0, character=6)
    hover_res = await server_module.hover(mock_ls, HoverParams(
        text_document=TextDocumentIdentifier(uri=uri), position=pos
    ))
    # Should NOT satisfy "Reactive Shorthand"
    # But might satisfy "Directive" if generic fallback is used?
    # Logic: if word matches known directive, return doc.
    # Else if word startswith $, return "Directive".
    
    # Wait, the user complained about <div $permanent> showing "Reactive Shorthand".
    # My new code:
    # elif word.startswith("$"): return "Directive"
    
    # So it will now say "Directive". Is that okay?
    # User said: "It also affects $attributes in HTML tags which is wholly incorrect."
    # AND "Message hovering over <div $permanent> is ... Reactive Shorthand ... Equivalent to permanent.value"
    #
    # PyWire uses $ for directives like $if.
    # Does PyWire use arbitrary $attributes?
    # If $permanent is NOT a valid directive, maybe we shouldn't show anything?
    # Or show "Unknown directive"?
    #
    # Existing directives are in `hover_docs` ($if, $show, $for, $key).
    #
    # My code currently does:
    # if word in hover_docs: return ...
    # ...
    # elif word.startswith("$"): return "**$foo**\n\nDirective."
    #
    # This seems safer than "Reactive Shorthand".
    # $permanent implies it IS a directive (custom or future).
    # If the user thinks $attributes is incorrect, maybe they mean they don't want ANY hover for unknown ones?
    # But usually $ indicates a directive in PyWire now.
    #
    # So it will now return None
    
    assert hover_res is None

@pytest.mark.asyncio
async def test_definition_reference_fallback(mock_ls, mock_ty_client):
    # Setup global state
    server_module.ty_client = mock_ty_client
    server_module.virtual_manager = Mock()
    server_module.virtual_manager.get_shadow_uri.return_value = "file:///shadow.py"

    uri = "file:///test.wire"
    text = """
---
my_var = 10
---
<input value={my_var}>
"""
    server_module.did_open(mock_ls, DidOpenTextDocumentParams(
        text_document=TextDocumentItem(
            uri=uri, language_id="pywire", version=1, text=text
        )
    ))

    # Fix the mock so reverse mapping works
    doc = server_module.documents[uri]
    server_module.virtual_manager.get_original_uri.return_value = uri
    server_module.virtual_manager.get_source_map.return_value = doc.source_map

    # Click exactly on '{' of value={my_var}
    # This position is not mapped directly, so it should trigger the fallback
    # Line 4 (0-indexed), character 13 is '{'
    pos = Position(line=4, character=13)
    
    # 1. Test Definition Fallback
    mock_ty_client.send_request.return_value = [{"uri": "file:///shadow.py", "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 6}}}]
    
    def_params = DefinitionParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=pos
    )
    result = await server_module.definition(mock_ls, def_params)
    
    # Verify send_request was called (meaning fallback found a mapped position)
    call_args = mock_ty_client.send_request.call_args
    assert call_args is not None
    method, _ = call_args[0]
    assert method == "textDocument/definition"
    assert result is not None

    # 2. Test References Fallback
    mock_ty_client.send_request.reset_mock()
    mock_ty_client.send_request.return_value = [{"uri": "file:///shadow.py", "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 6}}}]
    
    ref_params = ReferenceParams(
        text_document=TextDocumentIdentifier(uri=uri),
        position=pos,
        context={"includeDeclaration": True}
    )
    result = await server_module.references(mock_ls, ref_params)
    
    call_args = mock_ty_client.send_request.call_args
    assert call_args is not None
    method, _ = call_args[0]
    assert method == "textDocument/references"
    assert result is not None
