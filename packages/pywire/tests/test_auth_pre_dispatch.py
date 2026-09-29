"""The !auth guard must run BEFORE handler dispatch on non-render paths.

``BasePage.render()`` short-circuits on guard denial, but two dispatch
paths invoked handlers *before* any render: ``_handle_form_post`` (forged
``__pywire_handler`` / ``X-PyWire-Handler``) and the ``X-PyWire-Event``
JSON branch of ``_handle_request``. An anonymous forged POST on an
``!auth`` page executed handler side effects; the guard only redirected
afterwards. Every test here probes a side effect (a file written by the
handler) to prove dispatch never happened.
"""

import re
import shutil
import sys
import tempfile
from pathlib import Path

from starlette.testclient import TestClient

from pywire.auth import ClaimsPrincipal
from pywire.runtime.app import PyWire


def _auth_page(probe: Path) -> str:
    return (
        "!auth\n"
        "---\n"
        "def do_thing(data):\n"
        f"    open({str(probe)!r}, 'w').write('ran')\n"
        "---\n"
        "<p id='secret'>secret</p>\n"
        "<form method='post' @submit={do_thing}>\n"
        "  <input name='q' />\n"
        "</form>\n"
    )


class _ToggleApp(PyWire):
    """App whose principal flips between requests via ``auth_on``."""

    auth_on = False

    def get_user(self, request):
        if _ToggleApp.auth_on:
            return ClaimsPrincipal(is_authenticated=True)
        return None


def _make_app(pages: dict[str, str], cls=PyWire):
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    for name, content in pages.items():
        (pages_dir / f"{name}.wire").write_text(content)
    app = cls(pages_dir=str(pages_dir), interactive_server_mode=False)
    return app, test_dir


def _client(app):
    return TestClient(app, raise_server_exceptions=False)


def test_forged_hidden_handler_denied_before_dispatch(tmp_path):
    """No-JS floor: forged ``__pywire_handler`` must not run the handler."""
    probe = tmp_path / "probe"
    app, test_dir = _make_app({"guard": _auth_page(probe)})
    try:
        r = _client(app).post(
            "/guard",
            data={"__pywire_handler": "do_thing", "q": "1"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
        assert not probe.exists(), "handler ran before the auth guard"
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_forged_header_handler_denied_before_dispatch(tmp_path):
    probe = tmp_path / "probe"
    app, test_dir = _make_app({"guard": _auth_page(probe)})
    try:
        r = _client(app).post(
            "/guard",
            data={"q": "1"},
            headers={"X-PyWire-Handler": "do_thing"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
        assert not probe.exists(), "handler ran before the auth guard"
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_forged_event_json_denied_before_dispatch(tmp_path):
    """X-PyWire-Event JSON POST: SPA-nav response, no dispatch."""
    probe = tmp_path / "probe"
    app, test_dir = _make_app({"guard": _auth_page(probe)})
    try:
        r = _client(app).post(
            "/guard",
            json={"handler": "do_thing", "data": {}},
            headers={"X-PyWire-Event": "1"},
        )
        assert r.status_code == 200
        assert r.json() == {"type": "navigate", "path": "/login"}
        assert not probe.exists(), "handler ran before the auth guard"
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_allowed_form_post_still_dispatches(tmp_path):
    probe = tmp_path / "probe"
    _ToggleApp.auth_on = True
    app, test_dir = _make_app({"guard": _auth_page(probe)}, cls=_ToggleApp)
    try:
        r = _client(app).post(
            "/guard", data={"__pywire_handler": "do_thing", "q": "1"}
        )
        assert r.status_code == 200
        assert probe.exists(), "authenticated dispatch was blocked"
    finally:
        _ToggleApp.auth_on = False
        shutil.rmtree(test_dir, ignore_errors=True)


def test_allowed_event_json_still_dispatches(tmp_path):
    probe = tmp_path / "probe"
    _ToggleApp.auth_on = True
    app, test_dir = _make_app({"guard": _auth_page(probe)}, cls=_ToggleApp)
    try:
        r = _client(app).post(
            "/guard",
            json={"handler": "do_thing", "data": {}},
            headers={"X-PyWire-Event": "1"},
        )
        assert r.status_code == 200
        assert r.json().get("type") != "navigate"
        assert probe.exists(), "authenticated dispatch was blocked"
    finally:
        _ToggleApp.auth_on = False
        shutil.rmtree(test_dir, ignore_errors=True)


COMP_CHILD = (
    "---\n"
    "n = wire(0)\n"
    "\n"
    "def bump(data):\n"
    "    open(PROBE, 'w').write('ran')\n"
    "    n.value += 1\n"
    "---\n"
    "<button @click={bump}>{n}</button>\n"
)

COMP_PARENT = "!auth\n---\nfrom comp_child import CompChild\n---\n<CompChild />\n"


def test_forged_component_handler_denied_before_dispatch(tmp_path, monkeypatch):
    """The ``_comp:`` branch of _handle_form_post gets the same guard."""
    probe = tmp_path / "comp_probe"
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "comp_child.wire").write_text(
        COMP_CHILD.replace("PROBE", repr(str(probe)))
    )
    (pages_dir / "aparent.wire").write_text(COMP_PARENT)
    monkeypatch.syspath_prepend(str(pages_dir))
    _ToggleApp.auth_on = True
    app = _ToggleApp(pages_dir=str(pages_dir), interactive_server_mode=False)
    try:
        html = _client(app).get("/aparent").text
        key = re.search(r'_comp:([^:"]+):bump', html).group(1)

        _ToggleApp.auth_on = False
        r = _client(app).post(
            "/aparent",
            data={},
            headers={"X-PyWire-Handler": f"_comp:{key}:bump"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
        assert not probe.exists(), "component handler ran before the auth guard"
    finally:
        _ToggleApp.auth_on = False
        sys.modules.pop("comp_child", None)
        shutil.rmtree(test_dir, ignore_errors=True)
