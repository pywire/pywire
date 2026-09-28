"""ty diagnostics for a .wire file arrive per virtual file (shadow .py and stub .pyi)."""

from unittest.mock import Mock

import pytest
from pygls.lsp.server import LanguageServer

from pywire_language_server import server
from pywire_language_server.server import PyWireDocument, VirtualFileManager

WIRE_URI = "file:///app/page.wire"
TEXT = """!path '/'

---
from pywire import wire
count = wire(0)
---
<p>{undefined_name}</p>
"""


@pytest.fixture
def wired(monkeypatch):
    manager = VirtualFileManager("file:///app")
    doc = PyWireDocument(WIRE_URI, TEXT)
    shadow_uri = manager.get_shadow_uri(WIRE_URI)
    stub_uri = manager.get_stub_uri(WIRE_URI)
    manager.set_source_map(shadow_uri, doc.source_map)
    manager.set_source_map(stub_uri, doc.source_map)
    monkeypatch.setattr(server, "virtual_manager", manager)
    monkeypatch.setattr(server, "documents", {WIRE_URI: doc})
    monkeypatch.setattr(server, "ty_diagnostics", {})
    ls = Mock(spec=LanguageServer)
    return ls, doc, shadow_uri, stub_uri


def _ty_diagnostic(doc: PyWireDocument) -> dict:
    line = next(
        i
        for i, text in enumerate(doc.get_python_source().splitlines())
        if "undefined_name" in text
    )
    col = doc.get_python_source().splitlines()[line].index("undefined_name")
    return {
        "range": {
            "start": {"line": line, "character": col},
            "end": {"line": line, "character": col + len("undefined_name")},
        },
        "message": "Name `undefined_name` used when not defined",
        "severity": 1,
        "code": "unresolved-reference",
        "source": "ty",
    }


def _last_published(ls) -> list:
    params = ls.text_document_publish_diagnostics.call_args.args[0]
    assert params.uri == WIRE_URI
    return params.diagnostics


def test_empty_stub_publish_keeps_shadow_diagnostics(wired):
    ls, doc, shadow_uri, stub_uri = wired
    server._handle_ty_diagnostics(
        ls, {"uri": shadow_uri, "diagnostics": [_ty_diagnostic(doc)]}
    )
    server._handle_ty_diagnostics(ls, {"uri": stub_uri, "diagnostics": []})

    messages = [d.message for d in _last_published(ls)]
    assert "Name `undefined_name` used when not defined" in messages


def test_shadow_can_clear_its_own_diagnostics(wired):
    ls, doc, shadow_uri, _ = wired
    server._handle_ty_diagnostics(
        ls, {"uri": shadow_uri, "diagnostics": [_ty_diagnostic(doc)]}
    )
    server._handle_ty_diagnostics(ls, {"uri": shadow_uri, "diagnostics": []})

    assert not [d for d in _last_published(ls) if d.source == "ty"]


def test_same_problem_from_shadow_and_stub_is_reported_once(wired):
    ls, doc, shadow_uri, stub_uri = wired
    diag = _ty_diagnostic(doc)
    server._handle_ty_diagnostics(ls, {"uri": shadow_uri, "diagnostics": [diag]})
    server._handle_ty_diagnostics(ls, {"uri": stub_uri, "diagnostics": [diag]})

    ty_diags = [d for d in _last_published(ls) if d.source == "ty"]
    assert len(ty_diags) == 1


def test_finds_bundled_ty_without_path(monkeypatch):
    from pywire_language_server.ty import TyClient

    monkeypatch.setenv("PATH", "")
    executable = TyClient()._find_ty_executable()
    assert executable is not None
    assert executable.endswith(("ty", "ty.exe"))
