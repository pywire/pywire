import base64
from pathlib import Path

import pytest
from pywire.runtime.app import PyWire
from starlette.testclient import TestClient

LOCAL = "http://localhost"


def _dev_app(pages: Path) -> PyWire:
    app = PyWire(debug=True, pages_dir=str(pages))
    app._is_dev_mode = True
    return app


def _encoded(path: Path) -> str:
    return base64.urlsafe_b64encode(str(path).encode()).decode().rstrip("=")


def test_source_endpoint_requires_dev_mode_and_debug(tmp_path: Path) -> None:
    """/_pywire/source only works when BOTH debug=True AND _is_dev_mode=True."""
    test_file = tmp_path / "test.py"
    test_file.write_text("# content")

    # Case 1: debug=True, _is_dev_mode=False (e.g. pywire run with debug=True)
    app = PyWire(debug=True, pages_dir=str(tmp_path))
    client = TestClient(app, base_url=LOCAL)
    response = client.get(f"/_pywire/source?path={test_file}")
    assert response.status_code == 404

    # Case 2: debug=False, _is_dev_mode=True (should not happen practically if
    # logic aligns, but technically possible)
    app = PyWire(debug=False, pages_dir=str(tmp_path))
    app._is_dev_mode = True
    client = TestClient(app, base_url=LOCAL)
    response = client.get(f"/_pywire/source?path={test_file}")
    assert response.status_code == 404

    # Case 3: Both True
    client = TestClient(_dev_app(tmp_path), base_url=LOCAL)
    response = client.get(f"/_pywire/source?path={test_file}")
    assert response.status_code == 200
    assert response.text == "# content"


def test_file_endpoint_requires_dev_mode_and_debug(tmp_path: Path) -> None:
    """/_pywire/file/{encoded} gating."""
    test_file = tmp_path / "test.py"
    test_file.write_text("# content")

    # Case 1: production mode (debug=False, default)
    app = PyWire(debug=False, pages_dir=str(tmp_path))
    client = TestClient(app, base_url=LOCAL)
    response = client.get(f"/_pywire/file/{_encoded(test_file)}")
    assert response.status_code == 404

    # Case 2: Dev mode enabled
    client = TestClient(_dev_app(tmp_path), base_url=LOCAL)
    response = client.get(f"/_pywire/file/{_encoded(test_file)}/test.py")
    assert response.status_code == 200
    assert response.text == "# content"


def test_devtools_json_requires_dev_mode(tmp_path: Path) -> None:
    """DevTools JSON endpoint gating."""
    app = PyWire(debug=True, pages_dir=str(tmp_path))
    # _is_dev_mode defaults to False
    client = TestClient(app, base_url=LOCAL)
    response = client.get("/.well-known/appspecific/com.chrome.devtools.json")
    assert response.status_code == 404

    app._is_dev_mode = True
    client = TestClient(app, base_url=LOCAL)
    response = client.get("/.well-known/appspecific/com.chrome.devtools.json")
    assert response.status_code == 200
    assert "workspace" in response.json()


@pytest.mark.parametrize(
    "path",
    [
        "/_pywire/source?path={file}",
        "/_pywire/file/{encoded}",
        "/.well-known/appspecific/com.chrome.devtools.json",
    ],
)
@pytest.mark.parametrize("host", ["evil.example", "evil.example:3000", "10.0.0.5"])
def test_dev_routes_refuse_non_loopback_host(
    tmp_path: Path, path: str, host: str
) -> None:
    """DNS rebinding: a page on evil.example re-pointed at 127.0.0.1 sends
    its own hostname, so dev-only routes answer loopback names only."""
    test_file = tmp_path / "test.py"
    test_file.write_text("# content")
    client = TestClient(_dev_app(tmp_path), base_url=LOCAL)
    url = path.format(file=test_file, encoded=_encoded(test_file))
    assert client.get(url, headers={"host": host}).status_code == 404


@pytest.mark.parametrize("host", ["localhost:3000", "127.0.0.1:8000", "[::1]:3000"])
def test_dev_routes_answer_loopback_hosts(tmp_path: Path, host: str) -> None:
    test_file = tmp_path / "test.py"
    test_file.write_text("# content")
    client = TestClient(_dev_app(tmp_path), base_url=LOCAL)
    response = client.get(f"/_pywire/source?path={test_file}", headers={"host": host})
    assert response.status_code == 200


def test_source_endpoints_serve_only_project_sources(tmp_path: Path) -> None:
    """Files outside the project, and non-source files inside it, are not served."""
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text("<p>hi</p>\n")
    (pages / ".env").write_text("SECRET=1")
    (pages / "notes.txt").write_text("private")
    outside = tmp_path / "outside.py"
    outside.write_text("# outside the pages dir and the project root")
    escape = pages / ".." / "outside.py"

    client = TestClient(_dev_app(pages), base_url=LOCAL)

    ok = client.get(f"/_pywire/source?path={pages / 'index.wire'}")
    assert ok.status_code == 200
    assert ok.text == "<p>hi</p>\n"

    for target in (
        outside,
        escape,
        pages / ".env",
        pages / "notes.txt",
        Path("/etc/passwd"),
    ):
        response = client.get("/_pywire/source", params={"path": str(target)})
        assert response.status_code == 404, target
        assert client.get(f"/_pywire/file/{_encoded(target)}").status_code == 404


def test_source_endpoint_refuses_symlink_out_of_project(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    secret = tmp_path / "secret.py"
    secret.write_text("TOKEN = 'x'")
    (pages / "link.py").symlink_to(secret)

    client = TestClient(_dev_app(pages), base_url=LOCAL)
    response = client.get(f"/_pywire/source?path={pages / 'link.py'}")
    assert response.status_code == 404
