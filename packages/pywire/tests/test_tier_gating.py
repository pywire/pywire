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

ASYNC_HANDLER_PAGE = """---
count = wire(0)

async def bump():
    count.value += 1
---
<p id="c">{count}</p><button @click={bump()}>+</button>
"""


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
