"""GCP deploy target tests."""

from pathlib import Path
import sys
import types
import re
import jinja2
import msgpack
from pywire import PyWire

TEMPLATES = Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy"


def test_gcp_functions_round_trips_stateless_snapshot(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(
        "---\ncount = wire(0)\ndef increment():\n    count.value += 1\n---\n<p>{count}</p><button @click={increment()}>+</button>\n"
    )
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key="gcp-test")
    mod = types.ModuleType("gcp_fixture_app")
    mod.app = app
    sys.modules[mod.__name__] = mod
    sys.modules["_routes"] = types.ModuleType("_routes")
    source = (
        jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES / "gcp_functions"))
        .get_template("main.py.j2")
        .render(app_module=mod.__name__, app_attr="app")
    )
    ns = {}
    exec(compile(source, "main.py", "exec"), ns)

    class Request:
        method = "GET"
        path = "/"
        headers = {}
        query_string = b""

        def get_data(self):
            return b""

    body, status, headers = ns["pywire"](Request())
    assert status == 200 and "_pywire_snapshot" in body.decode()
    match = re.search(
        r'_pywire_snapshot" type="text/plain">(.*?)</script>', body.decode()
    )
    assert match
    event = msgpack.packb(
        {"path": "/", "handler": "increment", "data": {}, "snapshot": match.group(1)}
    )
    Request.method = "POST"
    Request.path = "/_pywire/stateless"
    Request.get_data = lambda self: event
    body, status, headers = ns["pywire"](Request())
    assert status == 200 and "regions" in msgpack.unpackb(body, raw=False)
    sys.modules.pop(mod.__name__, None)
