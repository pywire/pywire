"""Tests for the AWS Lambda stateless deploy handler template."""

import base64
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import jinja2
import msgpack
import pytest
import pywire
from pywire import PyWire

from pywire_cli.deploy import generate_faas_requirements
from pywire_cli.main import _install_aws_dependencies

TEMPLATES = (
    Path(__file__).parents[2] / "pywire-templates/src/pywire_templates/deploy/aws"
)


def _render(name: str, **context: str) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        keep_trailing_newline=True,
    )
    return env.get_template(name).render(**context)


def _load_handler(tmp_path: Path) -> tuple[object, dict]:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(
        "---\n"
        "count = wire(0)\n"
        "def increment():\n"
        "    count.value += 1\n"
        "---\n"
        '<p id="count">{count}</p><button @click={increment}>+</button>\n'
    )
    (pages / "cookies.wire").write_text(
        "---\nseen = wire('')\n\n@init\ndef load():\n"
        "    seen.value = self.request.cookies.get('hello', 'none')\n"
        "    self.set_cookie('a', '1')\n    self.set_cookie('b', '2')\n"
        '---\n<p id="seen">{seen}</p>\n'
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

    source = _render("handler.py.j2", app_module=module.__name__, app_attr="app")
    namespace: dict = {"__file__": str(tmp_path / "handler.py")}
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


def test_handler_enables_vendored_package_before_imports() -> None:
    source = _render("handler.py.j2", app_module="main", app_attr="app")
    path_line = 'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "package"))'
    assert path_line in source
    assert source.index(path_line) < source.index("from pywire.adapters.oneshot")
    assert 'event.get("queryStringParameters") or {}' in source
    assert "urlencode(" in source


def test_readme_packages_from_aws_deploy_directory() -> None:
    readme = _render("README.md.j2", project_name="demo", function_name="demo")
    assert "cd .pywire/deploy/aws" in readme
    assert "zip -r function.zip handler.py _routes.py _pywire_build package" in readme
    assert "x86_64" in readme and "Python 3.12" in readme
    assert "arm64" in readme
    # CreateApi takes --name; HTTP API Lambda integrations need a payload
    # version; a stage deploys nothing without --auto-deploy; and API
    # Gateway can't invoke the function until it is granted permission.
    assert "create-api --name demo" in readme
    assert "--payload-format-version 2.0" in readme
    assert "--auto-deploy" in readme
    assert "aws lambda add-permission" in readme


@pytest.mark.parametrize(
    ("target", "platform_dep"),
    [
        ("aws", None),
        ("azure", "azure-functions"),
        ("gcp_functions", "functions-framework"),
    ],
)
def test_requirements_pin_building_pywire_and_keep_app_deps(
    tmp_path: Path, target: str, platform_dep: str | None
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n"
        "dependencies = ['pywire[cli]>=0.15', 'httpx>=0.27', 'PyWire_Auth>=0.3']\n"
    )
    lines = generate_faas_requirements(tmp_path, target).split()
    # The prebuilt pages call into the pywire that compiled them, so the
    # app's own looser pywire requirement is replaced, not added.
    expected = [f"pywire=={pywire.__version__}", "httpx>=0.27", "PyWire_Auth>=0.3"]
    assert lines == ([platform_dep] if platform_dep else []) + expected


def test_requirements_without_pyproject(tmp_path: Path) -> None:
    lines = generate_faas_requirements(tmp_path, "aws").split()
    assert lines == [f"pywire=={pywire.__version__}"]


def test_uv_vendoring_targets_lambda_runtime(tmp_path: Path) -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/uv"),
        patch("subprocess.run") as run,
    ):
        _install_aws_dependencies(tmp_path / "requirements.txt", tmp_path / "package")
    command = run.call_args.args[0]
    assert command[1:3] == ["pip", "install"]
    assert "--python-platform" in command
    assert command[command.index("--python-platform") + 1] == "x86_64-manylinux2014"
    assert command[command.index("--python-version") + 1] == "3.12"


def test_pip_vendoring_targets_lambda_runtime(tmp_path: Path) -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run") as run,
    ):
        _install_aws_dependencies(tmp_path / "requirements.txt", tmp_path / "package")
    command = run.call_args.args[0]
    assert command[command.index("--platform") + 1] == "manylinux2014_x86_64"
    assert command[command.index("--only-binary") + 1] == ":all:"
    assert command[command.index("--python-version") + 1] == "3.12"


def test_lambda_handler_round_trips_stateless_snapshot(tmp_path: Path) -> None:
    handler, app_module = _load_handler(tmp_path)
    try:
        get = handler(_event("GET", "/"), None)
        assert get["statusCode"] == 200
        assert get["isBase64Encoded"] is True
        html = base64.b64decode(get["body"]).decode()
        assert "_pywire_snapshot" in html

        match = re.search(r'_pywire_snapshot" type="text/plain">(.*?)</script>', html)
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


def test_lambda_handler_passes_cookies_both_ways(tmp_path: Path) -> None:
    handler, app_module = _load_handler(tmp_path)
    try:
        # Payload 2.0 (HTTP API) moves request cookies to event["cookies"]
        # and takes response cookies from result["cookies"].
        event = {
            **_event("GET", "/cookies"),
            "version": "2.0",
            "cookies": ["hello=world"],
        }
        result = handler(event, None)
        assert result["statusCode"] == 200
        assert ">world</p>" in base64.b64decode(result["body"]).decode()
        assert sorted(c.split("=", 1)[0] for c in result["cookies"]) == ["a", "b"]
        assert "set-cookie" not in result["headers"]

        # Payload 1.0 (REST API) keeps Cookie in the headers and needs
        # multiValueHeaders for repeated Set-Cookie.
        event = _event("GET", "/cookies")
        event["headers"]["Cookie"] = "hello=rest"
        result = handler(event, None)
        assert ">rest</p>" in base64.b64decode(result["body"]).decode()
        cookies = result["multiValueHeaders"]["set-cookie"]
        assert sorted(c.split("=", 1)[0] for c in cookies) == ["a", "b"]
    finally:
        sys.modules.pop(app_module, None)
        sys.modules.pop("_routes", None)
