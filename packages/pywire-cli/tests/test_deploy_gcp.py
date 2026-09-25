"""GCP deploy target tests."""

import json
from pathlib import Path
import shutil
import subprocess
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


_ISOLATED_GCP_DRIVER = '''\
"""Boot the generated main.py from an isolated deploy-dir copy.

sys.path holds ONLY the deploy-dir copy and whatever the interpreter already
had for installed deps (stdlib + site-packages) — the build root is excluded,
so the app source can only resolve from inside the deploy dir.
"""
import json
import os
import re
import sys

import msgpack

deploy, guard = sys.argv[1], sys.argv[2]
sys.path[:] = [deploy] + [
    p for p in sys.path if p and p != guard and not p.startswith(guard + os.sep)
]

import main as entrypoint  # generated entrypoint — imports app source + _routes


class Request:
    method = "GET"
    path = "/"
    headers = {}
    query_string = b""

    def __init__(self, body=b""):
        self._body = body

    def get_data(self):
        return self._body


get_body, get_status, _ = entrypoint.pywire(Request())
text = get_body.decode() if isinstance(get_body, bytes) else get_body
match = re.search(r'_pywire_snapshot" type="text/plain">(.*?)</script>', text)
snapshot = match.group(1) if match else ""
Request.method = "POST"
Request.path = "/_pywire/stateless"
post_body, post_status, post_headers = entrypoint.pywire(
    Request(
        msgpack.packb(
            {"path": "/", "handler": "increment", "data": {}, "snapshot": snapshot}
        )
    )
)
print(
    json.dumps(
        {
            "get_status": get_status,
            "has_snapshot": bool(match),
            "post_status": post_status,
            "post_content_type": (post_headers or {}).get("content-type"),
            "post_regions": "regions" in msgpack.unpackb(post_body, raw=False),
        }
    )
)
'''


def test_gcp_functions_build_produces_self_contained_deploy_dir(
    tmp_path: Path,
) -> None:
    """Execute the generated entrypoint from an isolated copy of the deploy dir.

    File-existence asserts can't catch a missing app package — the generated
    `main.py` does `from <app_module> import app`, so the deploy dir must carry
    the app source and boot with only its own contents importable.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path.cwd()
        pages = root / "pages"
        pages.mkdir()
        (pages / "index.wire").write_text(
            "---\ncount = wire(0)\ndef increment():\n    count.value += 1\n---\n<p>{count}</p><button @click={increment()}>+</button>\n"
        )
        (root / "gcp_isolated_app.py").write_text(
            "from pywire import PyWire\n"
            "app = PyWire(pages_dir='pages', stateless=True, secret_key='test')\n"
        )
        (root / "pyproject.toml").write_text("[project]\nname='test'\n")
        result = runner.invoke(
            cli,
            ["build", "gcp_isolated_app:app", "--platform", "gcp-functions"],
        )
        assert result.exit_code == 0, result.output
        deploy_copy = tmp_path / "deploy"
        shutil.copytree(root / ".pywire" / "deploy" / "gcp_functions", deploy_copy)

    driver = tmp_path / "driver.py"
    driver.write_text(_ISOLATED_GCP_DRIVER)

    proc = subprocess.run(
        [sys.executable, str(driver), str(deploy_copy), str(tmp_path)],
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


def test_gcp_functions_build_warns_when_app_module_is_main() -> None:
    """functions-framework reserves main.py for the entrypoint.

    The build copies the app's root-level main.py into the deploy dir, then the
    generated entrypoint write clobbers it and `from main import app`
    self-imports the entrypoint — warn so the artifact isn't silently broken.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_app(Path.cwd(), module_name="main", stateless=True)
        sys.modules.pop("main", None)
        result = runner.invoke(
            cli, ["build", "main:app", "--platform", "gcp-functions"]
        )
        sys.modules.pop("main", None)
        assert result.exit_code == 0, result.output
        assert (
            "gcp-functions reserves main.py for its entrypoint — rename your app "
            "module (or use src/); the generated entrypoint will shadow it."
            in " ".join(result.output.split())
        )


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
