"""No-JS form floor (T27): `!no_interactive` pages must run `@submit`
handlers on a plain browser form POST.

Such pages still ship the client JS, but the client skips event wiring —
and a browser with JS disabled never had any. Either way the form submits
natively: ``application/x-www-form-urlencoded``, form fields only, no
custom headers. The server must run the handler and return a full
document. The JS-style POST (``X-PyWire-Handler`` header) keeps working.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

NO_JS_PAGE = """!no_interactive
---
name = wire('')

def save(data):
    name.value = " ".join(f"{k}={v}" for k, v in sorted(data.items()))
---
<p id="echo">[{name}]</p>
<form method="post" @submit={save}>
  <input name="name" />
  <button type="submit">Go</button>
</form>
"""


def _make_app(interactive_server_mode: bool):
    test_dir = tempfile.mkdtemp()
    pages_dir = Path(test_dir) / "pages"
    pages_dir.mkdir()
    (pages_dir / "form.wire").write_text(NO_JS_PAGE)
    app = PyWire(
        pages_dir=str(pages_dir), interactive_server_mode=interactive_server_mode
    )
    return app, test_dir


@pytest.fixture()
def app_and_dir():
    made = []

    def factory(interactive_server_mode: bool):
        app, test_dir = _make_app(interactive_server_mode)
        made.append(test_dir)
        return app

    yield factory
    for test_dir in made:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_form_renders_handler_hidden_input(app_and_dir):
    client = TestClient(app_and_dir(False), raise_server_exceptions=False)
    r = client.get("/form")
    assert r.status_code == 200
    assert 'name="__pywire_handler"' in r.text
    assert 'value="save"' in r.text


@pytest.mark.parametrize("interactive", [False, True])
def test_native_form_post_without_js_runs_handler(app_and_dir, interactive):
    client = TestClient(app_and_dir(interactive), raise_server_exceptions=False)
    # Exactly what a JS-disabled browser sends: urlencoded form fields,
    # no custom headers.
    r = client.post(
        "/form",
        data={"name": "world", "__pywire_handler": "save"},
    )
    assert r.status_code == 200
    # The echo shows the exact handler data — __pywire_handler is plumbing,
    # not form data, so it must never leak into what handlers see.
    assert "[name=world]" in r.text
    # Full document (init scripts + client bundle), not a body fragment.
    assert 'id="_pywire_spa_meta"' in r.text
    assert "pywire.core.min.js" in r.text


def test_js_style_post_with_header_still_works(app_and_dir):
    client = TestClient(app_and_dir(False), raise_server_exceptions=False)
    # httpFormSubmit sends all form fields (hidden input included) plus the
    # X-PyWire-Handler header. The header wins; the hidden field is dropped.
    r = client.post(
        "/form",
        data={"name": "js", "__pywire_handler": "save"},
        headers={"X-PyWire-Handler": "save"},
    )
    assert r.status_code == 200
    assert "[name=js]" in r.text
