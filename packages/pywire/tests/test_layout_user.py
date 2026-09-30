"""Layouts and components see the page's ``user``."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from starlette.testclient import TestClient

from pywire.runtime.app import PyWire


class _App(PyWire):
    def get_user(self, request_or_websocket: Any) -> Any:
        return SimpleNamespace(name="Ada")


def test_layout_and_component_read_the_page_user(tmp_path: Path):
    pages = tmp_path / "pages"
    components = tmp_path / "components"
    pages.mkdir()
    components.mkdir()
    (pages / "__layout__.wire").write_text(
        "<html><body><nav id='nav'>nav={user.name}</nav>{$render children}</body></html>\n"
    )
    (components / "badge.wire").write_text("<b id='badge'>badge={user.name}</b>\n")
    (pages / "index.wire").write_text(
        "---\nfrom components.badge import Badge\n---\n"
        "<p id='page'>page={user.name}</p><Badge />\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        with TestClient(_App(pages_dir=str(pages))) as client:
            html = client.get("/").text
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("components.badge", None)
        sys.modules.pop("components", None)
    assert "page=Ada" in html
    assert "nav=Ada" in html
    assert "badge=Ada" in html
