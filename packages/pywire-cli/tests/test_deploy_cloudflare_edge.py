"""Tests for the cloudflare-edge target (stateless plain Worker, no DOs)."""

import asyncio
import os
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import jinja2
import msgpack
from click.testing import CliRunner

from pywire_cli.main import cli

EDGE_TEMPLATES = (
    Path(__file__).parents[2]
    / "pywire-templates/src/pywire_templates/deploy/cloudflare_edge"
)


def _make_app_dir() -> None:
    """Create a minimal PyWire app + empty build manifest for generate_cf_bundle."""
    Path("main.py").write_text(
        "from unittest.mock import MagicMock\n"
        "app = MagicMock()\n"
        "app.pages_dir = 'pages'\n"
        "app.static_dir = None\n"
    )
    Path("pages").mkdir(exist_ok=True)
    manifest = Path(".pywire") / "build" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"entries": {}}')


class TestBuildCloudflareEdge:
    @patch("pywire.compiler.build.build_project")
    def test_build_emits_stateless_worker_bundle(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0,
            layouts=0,
            components=0,
            static_assets=0,
            out_dir=".pywire/build",
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_app_dir()
            result = runner.invoke(cli, ["build", "--platform", "cloudflare-edge"])
            assert result.exit_code == 0, result.output

            # entry.py drives one-shot requests through OneShotASGIAdapter
            entry = Path("entry.py").read_text()
            assert "OneShotASGIAdapter" in entry

            # wrangler.toml is a plain Worker: Python Workers, assets binding,
            # and NO Durable Objects
            wrangler = Path("wrangler.toml").read_text()
            assert "durable_objects" not in wrangler
            assert "python_workers" in wrangler

            # edge bundle carries no Durable Object class
            assert not Path("pywire_do.py").exists()

    @patch("pywire.compiler.build.build_project")
    def test_assets_go_under_base_path(self, mock_build: MagicMock) -> None:
        """Behind a Worker route like /demo/*, the assets binding sees
        /demo/static/app.css, so the files have to live under public/demo/."""
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, static_assets=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_app_dir()
            Path("static").mkdir()
            Path("static/app.css").write_text("body {}")
            Path("main.py").write_text(
                Path("main.py").read_text()
                + "app.static_dir = 'static'\n"
                + "app.static_url_path = '/static'\n"
                + "app.base_path = '/demo'\n"
            )
            # Earlier tests imported another main.py under the same name.
            sys.modules.pop("main", None)
            try:
                result = runner.invoke(cli, ["build", "--platform", "cloudflare-edge"])
            finally:
                sys.modules.pop("main", None)
            assert result.exit_code == 0, result.output

            public = Path(".pywire/deploy/public")
            assert (public / "demo/static/app.css").read_text() == "body {}"
            assert not (public / "static").exists()


class TestDeployCloudflareEdge:
    @patch("pywire.compiler.build.build_project")
    def test_deploy_writes_stateless_configs(self, mock_build: MagicMock) -> None:
        mock_build.return_value = MagicMock(
            pages=0, layouts=0, components=0, out_dir=".pywire/build"
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_app_dir()
            result = runner.invoke(cli, ["deploy", "--platform", "cloudflare-edge"])
            assert result.exit_code == 0, result.output

            assert "OneShotASGIAdapter" in Path("entry.py").read_text()
            assert "durable_objects" not in Path("wrangler.toml").read_text()
            assert not Path("pywire_do.py").exists()


def test_edge_entry_serves_stateless_app(tmp_path: Path, monkeypatch) -> None:
    """Run the generated entry.py against a real app with a stub `workers`."""
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(
        "---\ncount = wire(0)\ndef increment():\n    count.value += 1\n---\n"
        "<p>{count}</p><button @click={increment}>+</button>\n"
    )
    (pages / "cookies.wire").write_text(
        "---\nseen = wire('')\n\n@init\ndef load():\n"
        "    seen.value = self.request.cookies.get('hello', 'none')\n"
        "    self.set_cookie('a', '1')\n    self.set_cookie('b', '2')\n"
        '---\n<p id="seen">{seen}</p>\n'
    )
    # Like a real app: the secret comes from os.environ at import time.
    (tmp_path / "edge_fixture_app.py").write_text(
        "from pywire import PyWire\n"
        f"app = PyWire(pages_dir={str(pages)!r}, stateless=True)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "edge_fixture_app", raising=False)
    monkeypatch.delenv("PYWIRE_SECRET_KEY", raising=False)

    class Response:
        def __init__(self, body, status=200, headers=None):
            self.body, self.status, self.headers = body, status, headers

    class WorkerEntrypoint:
        def __init__(self, env):
            self.env = env

    workers = types.ModuleType("workers")
    workers.Response = Response  # type: ignore[attr-defined]
    workers.WorkerEntrypoint = WorkerEntrypoint  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "workers", workers)
    # The entry sets PYWIRE_PREBUILT, so PyWire() compiles nothing and the
    # bundle's _routes.py registers the pages; this one compiles them instead.
    (tmp_path / "_routes.py").write_text(
        "from edge_fixture_app import app\napp._load_pages()\n"
    )
    monkeypatch.delitem(sys.modules, "_routes", raising=False)

    source = (
        jinja2.Environment(loader=jinja2.FileSystemLoader(EDGE_TEMPLATES))
        .get_template("entry.py.j2")
        .render(app_module="edge_fixture_app", app_attr="app")
    )
    ns: dict = {"__file__": str(tmp_path / "entry.py")}
    # Python Workers only expose the secret on `env`, so importing the app
    # here (before any request) would raise for want of one.
    exec(compile(source, "entry.py", "exec"), ns)

    class Request:
        def __init__(self, method, url, body=b"", headers=None):
            self.method, self.url, self._body = method, url, body
            self.headers = {"accept-encoding": "gzip", **(headers or {})}

        async def bytes(self):
            return self._body

    monkeypatch.delenv("EDGE_FIXTURE_SETTING", raising=False)
    env = types.SimpleNamespace(
        PYWIRE_SECRET_KEY="edge-test-secret-at-least-32-bytes",
        # A Worker var or secret the app reads from os.environ.
        EDGE_FIXTURE_SETTING="on",
        # A binding that isn't a string stays out of os.environ.
        ASSETS=object(),
    )

    def fetch(*args, **kwargs):
        return asyncio.run(ns["Default"](env).fetch(Request(*args, **kwargs)))

    try:
        get = fetch("GET", "https://edge.test/")
        assert get.status == 200
        assert os.environ["EDGE_FIXTURE_SETTING"] == "on"
        assert "ASSETS" not in os.environ
        # The Workers runtime compresses by itself; the app must not have.
        assert "content-encoding" not in dict(get.headers)
        match = re.search(
            r'_pywire_snapshot" type="text/plain">(.*?)</script>', get.body.decode()
        )
        assert match

        event = msgpack.packb(
            {
                "path": "/",
                "handler": "increment",
                "data": {},
                "snapshot": match.group(1),
            }
        )
        post = fetch(
            "POST",
            "https://edge.test/_pywire/stateless",
            body=event,
            headers={"content-type": "application/x-msgpack"},
        )
        assert post.status == 200
        assert "regions" in msgpack.unpackb(post.body, raw=False)

        got = fetch(
            "GET", "https://edge.test/cookies", headers={"cookie": "hello=world"}
        )
        assert b">world</p>" in got.body
        cookies = [v for k, v in got.headers if k.lower() == "set-cookie"]
        assert sorted(c.split("=", 1)[0] for c in cookies) == ["a", "b"]
    finally:
        sys.modules.pop("edge_fixture_app", None)


def test_edge_entry_imports_a_src_layout_app(tmp_path: Path, monkeypatch) -> None:
    """src.main:app can import its sibling packages, as under `pywire dev`."""
    (tmp_path / "src" / "helpers").mkdir(parents=True)
    (tmp_path / "src" / "helpers" / "__init__.py").write_text("VALUE = 7\n")
    (tmp_path / "src" / "edge_src_app.py").write_text("from helpers import VALUE\n")
    workers = types.ModuleType("workers")
    workers.Response = object  # type: ignore[attr-defined]
    workers.WorkerEntrypoint = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "workers", workers)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in ("helpers", "src.edge_src_app"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    source = (
        jinja2.Environment(loader=jinja2.FileSystemLoader(EDGE_TEMPLATES))
        .get_template("entry.py.j2")
        .render(app_module="src.edge_src_app", app_attr="app")
    )
    exec(compile(source, "entry.py", "exec"), {"__file__": str(tmp_path / "entry.py")})

    assert sys.path[:2] == [str(tmp_path), str(tmp_path / "src")]
    import importlib

    try:
        assert importlib.import_module("src.edge_src_app").VALUE == 7
    finally:
        for name in ("helpers", "src", "src.edge_src_app"):
            sys.modules.pop(name, None)
