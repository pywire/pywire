"""Tests for the AWS Lambda stateless deploy handler template."""

import base64
import re
import sys
import types
from pathlib import Path

import jinja2
import msgpack
from pywire import PyWire

TEMPLATES = (
    Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy/aws"
)


def _load_handler(tmp_path: Path) -> tuple[object, dict]:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(
        "---\n"
        "count = wire(0)\n"
        "def increment():\n"
        "    count.value += 1\n"
        "---\n"
        '<p id="count">{count}</p><button @click={increment()}>+</button>\n'
    )
    app = PyWire(
        pages_dir=str(pages),
        stateless=True,
        secret_key="lambda-test-secret",
    )
    module = types.ModuleType("lambda_fixture_app")
    module.app = app  # type: ignore[attr-defined]
    sys.modules[module.__name__] = module
    sys.modules["_routes"] = types.ModuleType("_routes")

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        keep_trailing_newline=True,
    )
    source = env.get_template("handler.py.j2").render(
        app_module=module.__name__, app_attr="app"
    )
    namespace: dict = {}
    exec(compile(source, "handler.py", "exec"), namespace)
    return namespace["handler"], module.__name__


def _event(method: str, path: str, *, body: bytes = b"") -> dict:
    return {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/x-msgpack"},
        "body": base64.b64encode(body).decode(),
        "isBase64Encoded": True,
    }


def test_lambda_handler_round_trips_stateless_snapshot(tmp_path: Path) -> None:
    handler, app_module = _load_handler(tmp_path)
    try:
        get = handler(_event("GET", "/"), None)
        assert get["statusCode"] == 200
        assert "_pywire_snapshot" in get["body"]

        match = re.search(
            r'_pywire_snapshot" type="text/plain">(.*?)</script>', get["body"]
        )
        assert match is not None
        snapshot = match.group(1)
        event = msgpack.packb(
            {
                "path": "/",
                "handler": "increment",
                "data": {},
                "snapshot": snapshot,
            }
        )

        post = handler(_event("POST", "/_pywire/stateless", body=event), None)
        assert post["statusCode"] == 200
        assert post["isBase64Encoded"] is True
        message = msgpack.unpackb(base64.b64decode(post["body"]), raw=False)
        assert "regions" in message
    finally:
        sys.modules.pop(app_module, None)
        sys.modules.pop("_routes", None)
