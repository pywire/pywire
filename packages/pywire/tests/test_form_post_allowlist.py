"""Form POST dispatch must enforce the compile-time handler allowlist.

Routed from the Task 5 review: ``_handle_form_post`` used to look the
``X-PyWire-Handler`` name up with ``getattr`` and call it directly,
bypassing ``BasePage._dispatch_handler`` and its ``__event_handlers__``
allowlist — in non-interactive mode ``handler="render"`` was invocable
by a client.
"""

import shutil
import tempfile
from pathlib import Path

from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.page import BasePage

FORM_PAGE = (
    "---\n"
    "name = wire('')\n"
    "\n"
    "async def handle_submit(data):\n"
    "    name.value = data.get('name', '')\n"
    "---\n"
    "<p id='greeting'>Hello {name}</p>\n"
    "<form method='post' @submit={handle_submit}>\n"
    "  <input name='name' />\n"
    "</form>\n"
)


def _make_app(pages: dict[str, str]):
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    for name, content in pages.items():
        (pages_dir / f"{name}.wire").write_text(content)
    app = PyWire(pages_dir=str(pages_dir), interactive_server_mode=False)
    return app, test_dir


def test_form_post_rejects_unlisted_handler():
    app, test_dir = _make_app({"form": FORM_PAGE})
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/form", data={"name": "x"}, headers={"X-PyWire-Handler": "render"}
        )
        assert r.status_code == 400
        assert "not a registered event handler" in r.text
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_form_post_allows_listed_handler():
    app, test_dir = _make_app({"form": FORM_PAGE})
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/form",
            data={"name": "world"},
            headers={"X-PyWire-Handler": "handle_submit"},
        )
        assert r.status_code == 200
        assert "world" in r.text
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_hand_rolled_page_stays_permissive():
    touched = []

    class HandPage(BasePage):
        __route__ = "/hand"

        async def _render_template(self):
            return "<html><body><p>hand</p></body></html>"

        def touch(self, data):
            touched.append(dict(data))

    app, test_dir = _make_app({})
    try:
        app.router.add_route("/hand", HandPage)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/hand", data={"a": "1"}, headers={"X-PyWire-Handler": "touch"})
        assert r.status_code == 200
        assert touched == [{"a": "1"}]
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
