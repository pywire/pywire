from pathlib import Path

from pywire.runtime.app import PyWire
from starlette.testclient import TestClient


def test_interpolation_ignore_in_script_and_style(tmp_path: Path) -> None:
    """Verify that {} in script and style tags are treated as literal text."""
    page_content = """---
---
<div>
    <script>
        const x = {a: 1, b: 2};
        function test() { return {c: 3}; }
    </script>
    <style>
        body { color: red; }
        .class { font-size: 12px; }
    </style>
    <p>Real interpolation: {1 + 1}</p>
</div>
"""
    (tmp_path / "page.wire").write_text(page_content, encoding="utf-8")

    app = PyWire(str(tmp_path))
    client = TestClient(app)

    response = client.get("/page")
    assert response.status_code == 200
    content = response.text

    assert "const x = {a: 1, b: 2};" in content
    assert "body { color: red; }" in content
    assert "<p>Real interpolation: 2</p>" in content


def test_interpolation_node_explicit_render(tmp_path: Path) -> None:
    """Cover the InterpolationNode logic in TemplateCodegen (fallback logic)."""
    page_content = "!path '/standalone'\n--- \n--- \n{ 'hello' }"
    (tmp_path / "standalone.wire").write_text(page_content, encoding="utf-8")
    app = PyWire(str(tmp_path))
    client = TestClient(app)
    response = client.get("/standalone")
    assert "hello" in response.text


def test_multiple_event_handlers(tmp_path: Path) -> None:
    """Cover multiple event handler logic in template codegen."""
    page_content = """!path '/multi'
---
def fn1(): pass
def fn2(): pass
---

<button @click={fn1} @click.stop={fn2}>Click</button>
"""
    (tmp_path / "multi.wire").write_text(page_content.strip(), encoding="utf-8")
    app = PyWire(str(tmp_path))
    client = TestClient(app)
    response = client.get("/multi")
    assert response.status_code == 200
    assert "fn1" in response.text
    assert "fn2" in response.text


def test_reactive_attributes(tmp_path: Path) -> None:
    """Cover reactive attribute and boolean logic in template codegen."""
    page_content = """!path '/reactive'
---
is_disabled = True
is_required = False
label = "Test Label"
---

<input disabled={is_disabled} required={is_required} aria-label={label}>
"""
    (tmp_path / "reactive.wire").write_text(page_content.strip(), encoding="utf-8")
    app = PyWire(str(tmp_path))
    client = TestClient(app)
    response = client.get("/reactive")
    assert response.status_code == 200
    assert "disabled" in response.text
    assert "required" not in response.text
    assert 'aria-label="Test Label"' in response.text
