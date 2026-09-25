"""Azure Functions stateless deploy template tests."""

import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

from click.testing import CliRunner
import jinja2
import msgpack
from pywire import PyWire

from pywire_cli.main import cli

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
    assert isinstance(post.body, bytes)
    assert post.headers.get("content-type") == "application/x-msgpack"
    assert post.status_code == 200 and "regions" in msgpack.unpackb(
        post.body, raw=False
    )
    for name in (mod.__name__, "azure", "azure.functions", "_routes"):
        sys.modules.pop(name, None)


def test_azure_build_generates_deployable_artifact_set() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path.cwd()
        pages = root / "pages"
        pages.mkdir()
        (pages / "index.wire").write_text("<p>hello</p>\n")
        (root / "azure_build_app.py").write_text(
            "from pywire import PyWire\n"
            "app = PyWire(pages_dir='pages', stateless=True, secret_key='test')\n"
        )
        (root / "pyproject.toml").write_text("[project]\nname='test'\n")
        result = runner.invoke(
            cli,
            ["build", "azure_build_app:app", "--platform", "azure-functions"],
        )
        target = root / ".pywire" / "deploy" / "azure"

        assert result.exit_code == 0, result.output
        assert (target / "_routes.py").is_file()
        assert (target / "_pywire_build").is_dir()
        for name in (
            "function_app.py",
            "host.json",
            "local.settings.json",
            "requirements.txt",
            "README.md",
        ):
            assert (target / name).is_file()
        settings = json.loads((target / "local.settings.json").read_text())
        assert (
            settings["Values"]["PYWIRE_SECRET_KEY"] == ""
        )  # never ship a known secret
        assert settings["Values"]["AzureWebJobsFeatureFlags"] == "EnableWorkerIndexing"


_AZURE_FUNCTIONS_STUB = '''\
"""Minimal azure.functions stub for the isolated-entrypoint test."""


class FunctionApp:
    def route(self, **kwargs):
        return lambda fn: fn


class HttpAuthLevel:
    ANONYMOUS = "anonymous"


class HttpRequest:
    pass


class HttpResponse:
    def __init__(self, body, status_code=None, headers=None, mimetype=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers
        self.mimetype = mimetype
'''


_ISOLATED_AZURE_DRIVER = '''\
"""Boot the generated function_app.py from an isolated deploy-dir copy.

sys.path holds ONLY the deploy-dir copy, the azure.functions stub dir, and
whatever the interpreter already had for installed deps (stdlib +
site-packages) — the build root is excluded, so the app source can only
resolve from inside the deploy dir.
"""
import json
import os
import re
import sys

import msgpack

deploy, stubs, guard = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path[:] = [deploy, stubs] + [
    p for p in sys.path if p and p != guard and not p.startswith(guard + os.sep)
]

import function_app  # generated entrypoint — imports app source + _routes


class Request:
    def __init__(self, method, url, body=b""):
        self.method, self.url, self._body = method, url, body

    @property
    def headers(self):
        return {"content-type": "application/x-msgpack"}

    def get_body(self):
        return self._body


handler = function_app.pywire
get = handler(Request("GET", "https://example.test/"))
text = get.body.decode() if isinstance(get.body, bytes) else get.body
match = re.search(r'_pywire_snapshot" type="text/plain">(.*?)</script>', text)
snapshot = match.group(1) if match else ""
post = handler(
    Request(
        "POST",
        "https://example.test/_pywire/stateless",
        msgpack.packb(
            {"path": "/", "handler": "increment", "data": {}, "snapshot": snapshot}
        ),
    )
)
print(
    json.dumps(
        {
            "get_status": get.status_code,
            "has_snapshot": bool(match),
            "post_status": post.status_code,
            "post_content_type": (post.headers or {}).get("content-type"),
            "post_regions": "regions" in msgpack.unpackb(post.body, raw=False),
        }
    )
)
'''


def test_azure_build_produces_self_contained_deploy_dir(tmp_path: Path) -> None:
    """Execute the generated entrypoint from an isolated copy of the deploy dir.

    File-existence asserts can't catch a missing app package — the generated
    `function_app.py` does `from <app_module> import app`, so the deploy dir
    must carry the app source and boot with only its own contents importable.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path.cwd()
        pages = root / "pages"
        pages.mkdir()
        (pages / "index.wire").write_text(
            "---\ncount = wire(0)\ndef increment():\n    count.value += 1\n---\n<p>{count}</p><button @click={increment()}>+</button>\n"
        )
        (root / "azure_isolated_app.py").write_text(
            "from pywire import PyWire\n"
            "app = PyWire(pages_dir='pages', stateless=True, secret_key='test')\n"
        )
        (root / "pyproject.toml").write_text("[project]\nname='test'\n")
        result = runner.invoke(
            cli,
            ["build", "azure_isolated_app:app", "--platform", "azure-functions"],
        )
        assert result.exit_code == 0, result.output
        deploy_copy = tmp_path / "deploy"
        shutil.copytree(root / ".pywire" / "deploy" / "azure", deploy_copy)

    stubs = tmp_path / "stubs"
    (stubs / "azure").mkdir(parents=True)
    (stubs / "azure" / "__init__.py").write_text("")
    (stubs / "azure" / "functions.py").write_text(_AZURE_FUNCTIONS_STUB)
    driver = tmp_path / "driver.py"
    driver.write_text(_ISOLATED_AZURE_DRIVER)

    proc = subprocess.run(
        [sys.executable, str(driver), str(deploy_copy), str(stubs), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"entrypoint failed to boot:\n{proc.stderr}"
    round_trip = json.loads(proc.stdout)
    assert round_trip["get_status"] == 200 and round_trip["has_snapshot"]
    assert round_trip["post_status"] == 200
    assert round_trip["post_content_type"] == "application/x-msgpack"
    assert round_trip["post_regions"]
