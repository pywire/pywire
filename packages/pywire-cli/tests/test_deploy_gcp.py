"""GCP deploy target tests."""

from pathlib import Path
import sys
import types
import re

from click.testing import CliRunner
import jinja2
import msgpack
from pywire import PyWire

from pywire_cli.main import cli

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
    assert isinstance(body, bytes)
    assert headers.get("content-type") == "application/x-msgpack"
    assert status == 200 and "regions" in msgpack.unpackb(body, raw=False)
    sys.modules.pop(mod.__name__, None)
    sys.modules.pop("_routes", None)


def _make_app(root: Path, *, module_name: str, stateless: bool) -> None:
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text("---\ncount = wire(0)\n---\n<p>{count}</p>\n")
    (root / f"{module_name}.py").write_text(
        "from pywire import PyWire\n"
        f"app = PyWire(pages_dir='pages', stateless={stateless!r}, secret_key='test')\n"
    )
    (root / "pyproject.toml").write_text("[project]\nname='test'\n")


def test_gcp_functions_build_generates_deployable_artifact_set() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_app(Path.cwd(), module_name="gcp_functions_build_app", stateless=True)
        result = runner.invoke(
            cli,
            [
                "build",
                "gcp_functions_build_app:app",
                "--platform",
                "gcp-functions",
            ],
        )
        target = Path.cwd() / ".pywire" / "deploy" / "gcp_functions"

        assert result.exit_code == 0, result.output
        assert (target / "_routes.py").is_file()
        assert (target / "_pywire_build").is_dir()
        for name in ("main.py", "requirements.txt", "README.md"):
            assert (target / name).is_file()


def test_gcp_cloudrun_build_generates_docker_artifacts() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_app(Path.cwd(), module_name="gcp_cloudrun_build_app", stateless=False)
        result = runner.invoke(
            cli,
            ["build", "gcp_cloudrun_build_app:app", "--platform", "gcp-cloudrun"],
        )
        target = Path.cwd() / ".pywire" / "deploy" / "gcp_cloudrun"

        assert result.exit_code == 0, result.output
        assert (target / "Dockerfile").is_file()
        assert (target / "README.md").is_file()
        assert not (target / "cloudrun.yaml").exists()
