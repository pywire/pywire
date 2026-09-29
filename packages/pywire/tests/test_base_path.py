"""Serving an app under a URL prefix: ``base_path`` and host mounts.

The app is written as if it ran at ``/``; links, redirects, cookie paths and
the client's own URLs gain the prefix on the way out, and paths the browser
sends lose it on the way in.
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import msgpack
import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire
from pywire.runtime.base_path import (
    apply_base_path,
    cookie_path,
    normalize_base_path,
    rewrite_headers,
    rewrite_html,
    strip_base,
    with_base,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestNormalize:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, ""),
            ("", ""),
            ("/", ""),
            ("demo", "/demo"),
            ("/demo/", "/demo"),
            ("/a/b", "/a/b"),
        ],
    )
    def test_forms(self, value, expected):
        assert normalize_base_path(value) == expected

    @pytest.mark.parametrize("value", ["/a?b", "/a#b", "/a//b", "/a\\b"])
    def test_rejects_non_paths(self, value):
        with pytest.raises(ValueError):
            normalize_base_path(value)


class TestWithBase:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("/", "/demo/"),
            ("/chat", "/demo/chat"),
            ("/chat?x=1#top", "/demo/chat?x=1#top"),
            ("/demo", "/demo"),
            ("/demo/chat", "/demo/chat"),
            ("/demo?x=1", "/demo?x=1"),
            ("/demonstration", "/demo/demonstration"),
            ("https://example.com/x", "https://example.com/x"),
            ("//cdn.example.com/x.js", "//cdn.example.com/x.js"),
            ("chat", "chat"),
            ("#top", "#top"),
            ("?page=2", "?page=2"),
            ("mailto:a@b.c", "mailto:a@b.c"),
        ],
    )
    def test_urls(self, url, expected):
        assert with_base(url, "/demo") == expected

    def test_no_prefix_is_identity(self):
        assert with_base("/chat", "") == "/chat"

    def test_non_string_passes_through(self):
        assert with_base(None, "/demo") is None


def test_cookie_path():
    assert cookie_path("/", "/demo") == "/demo"
    assert cookie_path("/api", "/demo") == "/demo/api"
    assert cookie_path("/demo", "/demo") == "/demo"
    assert cookie_path("/", "") == "/"
    assert cookie_path(None, "/demo") is None


def test_strip_base():
    assert strip_base("/demo", "/demo") == "/"
    assert strip_base("/demo/", "/demo") == "/"
    assert strip_base("/demo/chat", "/demo") == "/chat"
    assert strip_base("/demonstration", "/demo") == "/demonstration"
    assert strip_base("/chat", "/demo") == "/chat"
    assert strip_base("/chat", "") == "/chat"


class TestApplyBasePath:
    def test_proxy_stripped_prefix(self):
        scope = {"type": "http", "path": "/chat", "raw_path": b"/chat", "root_path": ""}
        out = apply_base_path(scope, "/demo")
        assert (out["root_path"], out["path"], out["raw_path"]) == (
            "/demo",
            "/demo/chat",
            b"/demo/chat",
        )
        assert scope["path"] == "/chat"  # caller's scope untouched

    def test_proxy_kept_prefix(self):
        scope = {"type": "http", "path": "/demo/chat", "root_path": ""}
        out = apply_base_path(scope, "/demo")
        assert (out["root_path"], out["path"]) == ("/demo", "/demo/chat")

    def test_composes_with_mount(self):
        scope = {
            "type": "websocket",
            "path": "/app/_pywire/ws",
            "root_path": "/app",
            "app_root_path": "",
        }
        out = apply_base_path(scope, "/demo")
        assert out["root_path"] == "/demo/app"
        assert out["path"] == "/demo/app/_pywire/ws"
        assert out["app_root_path"] == "/demo"

    def test_server_root_path_already_set(self):
        # uvicorn --root-path /demo: nothing to add.
        scope = {"type": "http", "path": "/demo/chat", "root_path": "/demo"}
        assert apply_base_path(scope, "/demo") is scope

    def test_old_style_path_without_root(self):
        scope = {"type": "http", "path": "/chat", "root_path": "/app"}
        out = apply_base_path(scope, "/demo")
        assert (out["root_path"], out["path"]) == ("/demo/app", "/demo/app/chat")

    def test_lifespan_untouched(self):
        scope = {"type": "lifespan"}
        assert apply_base_path(scope, "/demo") is scope


class TestRewriteHtml:
    def test_url_attributes(self):
        html = (
            '<a href="/chat">c</a><img src="/static/a.png">'
            "<form action='/search'><button formaction=/go>go</button></form>"
            '<video poster="/p.jpg"></video><svg><use xlink:href="/i.svg#x"/></svg>'
        )
        out = rewrite_html(html, "/demo")
        assert '<a href="/demo/chat">' in out
        assert '<img src="/demo/static/a.png">' in out
        assert "action='/demo/search'" in out
        assert "formaction=/demo/go>" in out
        assert 'poster="/demo/p.jpg"' in out
        assert 'xlink:href="/demo/i.svg#x"' in out

    def test_leaves_other_urls_and_attributes(self):
        html = (
            '<a href="https://x.dev/a" title="/not-a-url" data-href="/x">x</a>'
            '<a href="//cdn/x">y</a><a href="#top">z</a><a href="rel">w</a>'
            '<a href="/demo/already">v</a>'
        )
        assert rewrite_html(html, "/demo") == html

    def test_srcset(self):
        out = rewrite_html(
            '<img srcset="/a.png 1x, /b.png 2x, https://c/c.png 3x">', "/p"
        )
        assert 'srcset="/p/a.png 1x, /p/b.png 2x, https://c/c.png 3x"' in out

    def test_raw_text_and_comments_untouched(self):
        html = (
            '<script src="/app.js">const a = \'<a href="/x">\'</script>'
            '<style>a { background: url("/bg.png") }</style>'
            '<textarea><a href="/x"></textarea>'
            '<!-- <a href="/x"> -->'
        )
        out = rewrite_html(html, "/demo")
        assert '<script src="/demo/app.js">' in out
        assert "const a = '<a href=\"/x\">'" in out
        assert 'url("/bg.png")' in out
        assert '<textarea><a href="/x"></textarea>' in out
        assert '<!-- <a href="/x"> -->' in out

    def test_opt_out(self):
        html = '<a href="/" data-pw-no-base>site</a><a href="/">app</a>'
        out = rewrite_html(html, "/demo")
        assert out == '<a href="/" data-pw-no-base>site</a><a href="/demo/">app</a>'

    def test_quoted_greater_than(self):
        out = rewrite_html('<a data-x="a>b" href="/x">x</a>', "/demo")
        assert out == '<a data-x="a>b" href="/demo/x">x</a>'

    def test_no_prefix_is_identity(self):
        html = '<a href="/x">x</a>'
        assert rewrite_html(html, "") is html


def test_rewrite_headers():
    headers = [
        (b"location", b"/login?next=/x"),
        (b"set-cookie", b"sid=1; Path=/; HttpOnly"),
        (b"set-cookie", b"pref=dark"),
        (b"set-cookie", b"other=1; path=/demo/api"),
        (b"content-type", b"text/html"),
    ]
    out = dict((k, []) for k, _ in headers)
    for k, v in rewrite_headers(headers, "/demo"):
        out[k].append(v.decode())
    assert out[b"location"] == ["/demo/login?next=/x"]
    assert out[b"set-cookie"] == [
        "sid=1; Path=/demo; HttpOnly",
        "pref=dark; Path=/demo",
        "other=1; path=/demo/api",
    ]
    assert out[b"content-type"] == ["text/html"]


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

INDEX = """---
def leave():
    navigate("/about")

def remember():
    set_cookie("pref", "dark")
---
<a id="about" href="/about">About</a>
<a id="ext" href="https://example.com/x">ext</a>
<a id="site" href="/" data-pw-no-base>site</a>
<link rel="stylesheet" href={asset("app.css")}>
<form action="/search"><button formaction="/go">go</button></form>
<button @click={leave}>leave</button>
<button @click={remember}>remember</button>
<script>const raw = "/raw";</script>
<p id="base">{base_path}</p>
"""

ABOUT = """<p>About</p><a id="home" href="/">Home</a>"""

COOKIE = """---
@init
def load():
    set_cookie("pref", "dark")
---
<p>cookie</p>
"""


class RedirectMiddleware(BaseHTTPMiddleware):
    """Sends /private to /login, like an auth middleware, and sets a cookie
    on /cookie."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.endswith("/private"):
            return RedirectResponse("/login", status_code=302)
        response = await call_next(request)
        if request.url.path.endswith("/cookie"):
            response.set_cookie("mw", "1", path="/")
        return response


@pytest.fixture()
def project():
    root = Path(tempfile.mkdtemp())
    pages = root / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text(INDEX)
    (pages / "about.wire").write_text(ABOUT)
    (pages / "cookie.wire").write_text(COOKIE)
    (pages / "private.wire").write_text("<p>private</p>")
    (pages / "login.wire").write_text("<p>login</p>")
    static = root / "static"
    static.mkdir()
    (static / "app.css").write_text("body{}")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _app(project: Path, **kwargs: Any) -> PyWire:
    return PyWire(
        pages_dir=str(project / "pages"),
        static_dir=str(project / "static"),
        middleware=[RedirectMiddleware],
        **kwargs,
    )


def _meta(html: str) -> dict:
    m = re.search(
        r'<script id="_pywire_spa_meta" type="application/json">(.*?)</script>', html
    )
    assert m
    return json.loads(m.group(1))


def _recv(ws: Any) -> dict:
    while True:
        data = msgpack.unpackb(ws.receive_bytes(), raw=False)
        if data["type"] != "console":
            return data


def _init(ws: Any, path: str) -> dict:
    assert _recv(ws)["type"] == "init"
    ws.send_bytes(msgpack.packb({"type": "init", "path": path}))
    return _recv(ws)


def _send(ws: Any, message: dict) -> dict:
    ws.send_bytes(msgpack.packb(message))
    return _recv(ws)


def _assert_prefixed_page(html: str, prefix: str) -> None:
    assert f'id="about" href="{prefix}/about"' in html
    assert 'id="ext" href="https://example.com/x"' in html
    assert 'id="site" href="/" data-pw-no-base' in html
    assert f'href="{prefix}/static/app.css?v=' in html
    assert f'action="{prefix}/search"' in html
    assert f'formaction="{prefix}/go"' in html
    assert 'const raw = "/raw";' in html
    assert re.search(rf'<p id="base"[^>]*>{prefix}</p>', html)
    assert f'src="{prefix}/_pywire/static/' in html
    meta = _meta(html)
    assert meta["mount_path"] == prefix
    assert f"{prefix}/" in meta["all_paths"]
    assert f"{prefix}/about" in meta["all_paths"]
    assert meta["static_path"] == f"{prefix}/static"


# ---------------------------------------------------------------------------
# base_path behind a proxy
# ---------------------------------------------------------------------------


class TestBasePathApp:
    @pytest.fixture()
    def client(self, project):
        return TestClient(
            _app(project, base_path="/demo"), raise_server_exceptions=False
        )

    @pytest.mark.parametrize("path", ["/", "/demo/", "/demo"])
    def test_pages_render_with_prefixed_urls(self, client, path):
        # The proxy may strip the prefix ("/") or pass it through.
        r = client.get(path)
        assert r.status_code == 200
        _assert_prefixed_page(r.text, "/demo")

    @pytest.mark.parametrize("path", ["/static/app.css", "/demo/static/app.css"])
    def test_static_files(self, client, path):
        assert client.get(path).text == "body{}"

    def test_client_script_served(self, client):
        html = client.get("/").text
        src = re.search(r'src="(/demo/_pywire/static/[^"]+)"', html).group(1)
        assert client.get(src).status_code == 200

    def test_redirect_location(self, client):
        r = client.get("/private", follow_redirects=False)
        assert r.headers["location"] == "/demo/login"

    def test_cookie_path_over_http(self, client):
        r = client.get("/cookie")
        cookies = r.headers.get_list("set-cookie")
        assert len(cookies) == 2  # the page's and the middleware's
        assert all("Path=/demo" in c for c in cookies)

    def test_env_var(self, project, monkeypatch):
        monkeypatch.setenv("PYWIRE_BASE_PATH", "/from-env/")
        app = _app(project)
        assert app.base_path == "/from-env"
        html = TestClient(app).get("/").text
        assert 'href="/from-env/about"' in html

    def test_argument_beats_env_var(self, project, monkeypatch):
        monkeypatch.setenv("PYWIRE_BASE_PATH", "/from-env")
        assert _app(project, base_path="").base_path == ""

    def test_live_page(self, client):
        with client.websocket_connect("/_pywire/ws") as ws:
            ack = _init(ws, "/demo/")
            assert ack["type"] == "init_ack"

            nav = _send(
                ws, {"type": "event", "handler": "leave", "path": "/demo/", "data": {}}
            )
            assert (nav["type"], nav["path"]) == ("navigate", "/demo/about")

            upd = _send(ws, {"type": "relocate", "path": "/demo/about"})
            assert upd["type"] == "update"
            assert 'id="home" href="/demo/"' in upd["html"]

            back = _send(ws, {"type": "relocate", "path": "/demo/"})
            assert 'id="about" href="/demo/about"' in back["html"]

            denied = _send(ws, {"type": "relocate", "path": "/demo/private"})
            assert (denied["type"], denied["path"]) == ("navigate", "/demo/login")

    def test_cookie_path_over_websocket(self, client):
        with client.websocket_connect("/_pywire/ws") as ws:
            _init(ws, "/demo/")
            upd = _send(
                ws,
                {"type": "event", "handler": "remember", "path": "/demo/", "data": {}},
            )
            cmds = [c for c in upd.get("commands", []) if c["cmd"] == "set_cookie"]
            assert cmds and cmds[0]["args"]["path"] == "/demo"

    def test_relocate_cookie_path(self, client):
        with client.websocket_connect("/_pywire/ws") as ws:
            _init(ws, "/demo/")
            upd = _send(ws, {"type": "relocate", "path": "/demo/cookie"})
            cmds = {
                c["args"]["key"]: c["args"]
                for c in upd.get("commands", [])
                if c["cmd"] == "set_cookie"
            }
            assert cmds["mw"]["path"] == "/demo"


# ---------------------------------------------------------------------------
# Mounted in a host app
# ---------------------------------------------------------------------------


def _host(pywire: PyWire, mount: str) -> Starlette:
    async def api(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    host = Starlette(routes=[Route("/api/ping", api)])
    host.router.routes.append(Mount(mount, app=pywire.as_asgi(host)))
    return host


class TestMounted:
    @pytest.fixture()
    def client(self, project):
        return TestClient(
            _host(_app(project), "/realtime"), raise_server_exceptions=False
        )

    def test_pages_render_with_prefixed_urls(self, client):
        r = client.get("/realtime/")
        assert r.status_code == 200
        _assert_prefixed_page(r.text, "/realtime")
        assert client.get("/api/ping").json() == {"ok": True}

    def test_redirect_location(self, client):
        r = client.get("/realtime/private", follow_redirects=False)
        assert r.headers["location"] == "/realtime/login"

    def test_live_page_through_host(self, client):
        with client.websocket_connect("/realtime/_pywire/ws") as ws:
            assert _init(ws, "/realtime/about")["type"] == "init_ack"

            upd = _send(ws, {"type": "relocate", "path": "/realtime/"})
            assert upd["type"] == "update"
            assert 'id="about" href="/realtime/about"' in upd["html"]

            denied = _send(ws, {"type": "relocate", "path": "/realtime/private"})
            assert (denied["type"], denied["path"]) == ("navigate", "/realtime/login")

    def test_base_path_composes_with_mount(self, project):
        client = TestClient(_host(_app(project, base_path="/demo"), "/app"))
        html = client.get("/app/").text
        _assert_prefixed_page(html, "/demo/app")


class TestAtRoot:
    def test_nothing_changes_without_a_prefix(self, project):
        html = TestClient(_app(project)).get("/").text
        _assert_prefixed_page(html, "")


# ---------------------------------------------------------------------------
# Stateless mode
# ---------------------------------------------------------------------------

STATELESS_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"


@pytest.mark.parametrize("page_path", ["/", "/demo/"])
def test_stateless_events_under_base_path(page_path):
    app = PyWire(
        pages_dir=str(STATELESS_PAGES),
        stateless=True,
        secret_key="test-secret-key-at-least-32-bytes",
        base_path="/demo",
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        html = client.get(page_path).text
        blob = html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[
            0
        ]
        # The browser is at /demo/ either way and posts to the prefixed
        # endpoint, which the proxy may or may not strip.
        for endpoint in ("/_pywire/stateless", "/demo/_pywire/stateless"):
            r = client.post(
                endpoint,
                content=msgpack.packb(
                    {
                        "path": "/demo/",
                        "handler": "increment",
                        "data": {},
                        "snapshot": blob,
                    }
                ),
                headers={"Content-Type": "application/x-msgpack"},
            )
            assert r.status_code == 200, r.content
            msg = msgpack.unpackb(r.content, raw=False)
            assert any("1" in reg["html"] for reg in msg.get("regions", []))
