"""Tier gating: ``{$await}`` template blocks are stateful-only.

Stateless apps own no timeline between requests, so a page containing
``{$await}`` must fail at compile/build time with an actionable error —
not silently ship fallback text. ``async def`` event *handlers* stay
valid in stateless (they are awaited inside the request).
"""

from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.compiler.build import build_project
from pywire.compiler.tier_gate import set_stateless_tier
from pywire.runtime.app import PyWire

SECRET = "test-secret-key"

AWAIT_PAGE = """---
import asyncio

async def slow_thing():
    await asyncio.sleep(10)
    return "done"
---
{$await slow_thing()}loading...{$then result}{result}{/await}
"""

NESTED_AWAIT_PAGE = """---
import asyncio

async def slow_thing():
    await asyncio.sleep(10)
    return "done"

rows = wire([1, 2])
---
{$for row in rows.value, key=row}<div>{$await slow_thing()}loading...{$then result}{result}{/await}</div>{/for}
"""

ASYNC_HANDLER_PAGE = """---
count = wire(0)

async def bump():
    count.value += 1
---
<p id="c">{count}</p><button @click={bump()}>+</button>
"""

SLOW_COMPONENT = """---
import asyncio

async def slow_thing():
    await asyncio.sleep(10)
    return "done"
---
<div>{$await slow_thing()}loading...{$then result}{result}{/await}</div>
"""

PAGE_A = """---
from components.SlowPanel import SlowPanel
---
<h1>A</h1><SlowPanel />
"""

PAGE_B = """<h1>B</h1>
"""

PUSH_STATE_PAGE = """---
from pywire import wire

progress = wire(0)

async def run():
    progress.value += 1
    await self.push_state()
---
<p id="p">{progress}</p><button @click={run()}>go</button>
"""

AUTH_PAGE = """<p>{$auth claims=[("role", "admin")]}PENDING-VIEW{$then ok}RESOLVED-{ok}{/auth}</p>
"""


def _closure_project(tmp_path: Path, with_page_a: bool = True) -> Path:
    """tmp project: components/SlowPanel.wire ({$await}) + pages using it or not."""
    pages = tmp_path / "pages"
    pages.mkdir()
    components = tmp_path / "components"
    components.mkdir()
    (components / "SlowPanel.wire").write_text(SLOW_COMPONENT)
    if with_page_a:
        (pages / "a.wire").write_text(PAGE_A)
    (pages / "b.wire").write_text(PAGE_B)
    return pages


@pytest.fixture()
def pages_dir(tmp_path: Path) -> Path:
    pages = tmp_path / "pages"
    pages.mkdir()
    return pages


@pytest.fixture(autouse=True)
def _reset_tier():
    yield
    set_stateless_tier(False)


def test_stateless_app_rejects_await_page_at_startup(pages_dir: Path):
    (pages_dir / "slow.wire").write_text(AWAIT_PAGE)
    app = PyWire(
        pages_dir=str(pages_dir), stateless=True, secret_key=SECRET, debug=True
    )
    with TestClient(app) as client:
        r = client.get("/slow")
    assert r.status_code == 500 or "poll" in r.text
    assert "slow.wire" in r.text


def test_build_fails_for_await_page_in_stateless_app(pages_dir: Path, tmp_path: Path):
    (pages_dir / "slow.wire").write_text(AWAIT_PAGE)
    # PyWire(...) sets the tier flag; the build then compiles every page.
    PyWire(pages_dir=str(pages_dir), stateless=True, secret_key=SECRET)
    with pytest.raises(Exception) as excinfo:
        build_project(pages_dir=pages_dir, out_dir=tmp_path / "build")
    msg = str(excinfo.value)
    assert "slow.wire" in msg
    assert "@poll" in msg
    assert "stateful" in msg.lower()


def test_stateless_app_rejects_nested_await_page(pages_dir: Path, tmp_path: Path):
    # {$await} buried inside a {$for} iteration body must still be caught:
    # the gate walks the AST recursively.
    (pages_dir / "nested.wire").write_text(NESTED_AWAIT_PAGE)
    PyWire(pages_dir=str(pages_dir), stateless=True, secret_key=SECRET)
    with pytest.raises(Exception) as excinfo:
        build_project(pages_dir=pages_dir, out_dir=tmp_path / "build")
    assert "nested.wire" in str(excinfo.value)


def test_build_error_names_page_for_component_closure(tmp_path: Path):
    # Headline closure case: a shared component with {$await} must fail the
    # page whose closure uses it, naming the page and the chain — not just
    # the component file.
    pages = _closure_project(tmp_path)
    PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    with pytest.raises(Exception) as excinfo:
        build_project(pages_dir=pages, out_dir=tmp_path / "build")
    msg = str(excinfo.value)
    assert "a.wire" in msg
    assert "SlowPanel.wire" in msg
    assert "@poll" in msg
    # Honesty: the error must state what the static scan cannot see.
    assert "imported helpers" in msg


def test_unused_await_component_builds_clean(tmp_path: Path):
    # The same component on disk, but no page's closure uses it -> clean build.
    pages = _closure_project(tmp_path, with_page_a=False)
    PyWire(pages_dir=str(pages), stateless=True, secret_key=SECRET)
    summary = build_project(pages_dir=pages, out_dir=tmp_path / "build")
    assert summary.pages == 1


def test_dev_render_names_page_for_component_closure(tmp_path: Path):
    pages = _closure_project(tmp_path)
    app = PyWire(
        pages_dir=str(pages), stateless=True, secret_key=SECRET, debug=True
    )
    with TestClient(app) as client:
        r = client.get("/a")
    assert r.status_code == 500 or "poll" in r.text
    assert "a.wire" in r.text
    assert "SlowPanel.wire" in r.text


def test_build_fails_for_push_state_in_handler(pages_dir: Path, tmp_path: Path):
    # push_state() in a handler body is a push feature when statically visible.
    (pages_dir / "streamer.wire").write_text(PUSH_STATE_PAGE)
    PyWire(pages_dir=str(pages_dir), stateless=True, secret_key=SECRET)
    with pytest.raises(Exception) as excinfo:
        build_project(pages_dir=pages_dir, out_dir=tmp_path / "build")
    msg = str(excinfo.value)
    assert "streamer.wire" in msg
    assert "push_state" in msg
    assert "@poll" in msg


def test_stateful_app_allows_push_state(pages_dir: Path, tmp_path: Path):
    # Non-stateless apps are unaffected: nothing to enforce.
    (pages_dir / "streamer.wire").write_text(PUSH_STATE_PAGE)
    PyWire(pages_dir=str(pages_dir), secret_key=SECRET)
    summary = build_project(pages_dir=pages_dir, out_dir=tmp_path / "build")
    assert summary.pages == 1


def test_stateless_build_allows_auth_page(pages_dir: Path, tmp_path: Path):
    # {$auth} resolves inline on stateless post-T31 — plain tier, builds clean.
    (pages_dir / "authy.wire").write_text(AUTH_PAGE)
    PyWire(pages_dir=str(pages_dir), stateless=True, secret_key=SECRET)
    summary = build_project(pages_dir=pages_dir, out_dir=tmp_path / "build")
    assert summary.pages == 1


def test_stateful_app_compiles_await_page(pages_dir: Path):
    (pages_dir / "slow.wire").write_text(AWAIT_PAGE)
    app = PyWire(pages_dir=str(pages_dir), secret_key=SECRET)
    with TestClient(app) as client:
        r = client.get("/slow")
    assert r.status_code == 200
    assert "loading..." in r.text


def test_stateless_async_handler_still_works(pages_dir: Path):
    (pages_dir / "index.wire").write_text(ASYNC_HANDLER_PAGE)
    app = PyWire(pages_dir=str(pages_dir), stateless=True, secret_key=SECRET)
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        blob = r.text.split('_pywire_snapshot" type="text/plain">')[1].split(
            "</script>"
        )[0]
        r = client.post(
            "/_pywire/stateless",
            content=msgpack.packb(
                {"path": "/", "handler": "bump", "data": {}, "snapshot": blob}
            ),
            headers={"Content-Type": "application/x-msgpack"},
        )
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert any("1" in reg["html"] for reg in msg.get("regions", []))
