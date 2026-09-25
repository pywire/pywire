"""Tests for the AWS Lambda stateless deploy handler template."""

import base64
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import jinja2
import msgpack
from pywire import PyWire

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


def test_requirements_pin_oneshot_release() -> None:
    assert _render("requirements.txt.j2").strip() == "pywire>=0.15.0"


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
