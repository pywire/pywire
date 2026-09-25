"""Azure Functions stateless deploy template tests."""

import re
import sys
import types
from pathlib import Path
import jinja2
import msgpack
from pywire import PyWire

TEMPLATES = (
    Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy/azure"
)


def test_azure_function_app_round_trips_stateless_snapshot(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(
        "---\ncount = wire(0)\ndef increment():\n    count.value += 1\n---\n<p>{count}</p><button @click={increment()}>+</button>\n"
    )
    app = PyWire(pages_dir=str(pages), stateless=True, secret_key="azure-test")
    mod = types.ModuleType("azure_fixture_app")
    mod.app = app
    sys.modules[mod.__name__] = mod
    sys.modules["_routes"] = types.ModuleType("_routes")
    azure = types.ModuleType("azure.functions")

    class FunctionApp:
        def route(self, **kwargs):
            return lambda fn: fn

    class HttpRequest:
        def __init__(self, method, url, body=b""):
            self.method, self.url, self._body = method, url, body

        @property
        def headers(self):
            return {"content-type": "application/x-msgpack"}

        def get_body(self):
            return self._body

    class HttpResponse:
        def __init__(self, body, status_code, headers=None, mimetype=None):
            self.body, self.status_code, self.headers, self.mimetype = (
                body,
                status_code,
                headers,
                mimetype,
            )

    class HttpAuthLevel:
        ANONYMOUS = "anonymous"

    azure.FunctionApp, azure.HttpRequest, azure.HttpResponse, azure.HttpAuthLevel = (
        FunctionApp,
        HttpRequest,
        HttpResponse,
        HttpAuthLevel,
    )
    sys.modules["azure"] = types.ModuleType("azure")
    sys.modules["azure.functions"] = azure
    source = (
        jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES))
        .get_template("function_app.py.j2")
        .render(app_module=mod.__name__, app_attr="app")
    )
    ns = {}
    exec(compile(source, "function_app.py", "exec"), ns)
    handler = ns["pywire"]
    get = handler(HttpRequest("GET", "https://example.test/"))
    assert get.status_code == 200 and "_pywire_snapshot" in get.body.decode()
    match = re.search(
        r'_pywire_snapshot" type="text/plain">(.*?)</script>', get.body.decode()
    )
    assert match
    event = msgpack.packb(
        {"path": "/", "handler": "increment", "data": {}, "snapshot": match.group(1)}
    )
    post = handler(HttpRequest("POST", "https://example.test/_pywire/stateless", event))
    assert post.status_code == 200 and "regions" in msgpack.unpackb(
        post.body, raw=False
    )
    for name in (mod.__name__, "azure", "azure.functions"):
        sys.modules.pop(name, None)
