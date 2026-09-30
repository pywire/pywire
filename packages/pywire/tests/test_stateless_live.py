"""Stateless pages and shared state (module-level wires, producers).

A stateless page is rebuilt from its snapshot on every request, so nothing
marks a region dirty when another user writes shared state. The endpoint
re-renders every region that reads shared state on every request, drops the
ones the client already shows, and tells the client how often to refresh
(``PyWire(live_every=...)`` or the page's ``!live`` directive).
"""

import re
import sys
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.app import PyWire
from pywire.runtime.snapshot_codec import decode_snapshot

SECRET = "test-secret-key-at-least-32-bytes"
_MSGPACK = {"Content-Type": "application/x-msgpack"}

SHARED_MODULE = """\
from pywire import derived, producer, wire

votes = wire(0)
doubled = derived(lambda: votes.value * 2)
_ticks = iter(range(100, 10_000))
ticker = producer(0, lambda set_value: set_value(next(_ticks)))
"""

VOTES_PAGE = """\
{directive}---
import live_shared
mine = wire(0)

def vote():
    live_shared.votes.value += 1

def bump():
    mine.value += 1
---
<p id="votes">Votes: {{live_shared.votes.value}}</p>
<p id="mine">Mine: {{mine}}</p>
<button @click={{vote}}>vote</button>
<button @click={{bump}}>bump</button>
"""


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A pages dir plus a fresh ``live_shared`` module on sys.path."""
    (tmp_path / "live_shared.py").write_text(SHARED_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "live_shared", raising=False)
    pages = tmp_path / "pages"
    pages.mkdir()
    return tmp_path


def _write(project: Path, name: str, source: str) -> None:
    (project / "pages" / name).write_text(source)


def _app(project: Path, **kwargs) -> PyWire:
    kwargs.setdefault("live_every", 5)
    return PyWire(
        pages_dir=str(project / "pages"), stateless=True, secret_key=SECRET, **kwargs
    )


def _tag(html: str) -> re.Match:
    match = re.search(
        r'<script id="_pywire_snapshot" type="text/plain"'
        r'(?: data-live-every="(\d+)")?>([^<]*)</script>',
        html,
    )
    assert match, "no snapshot tag"
    return match


def _live_every(html: str):
    value = _tag(html)[1]
    return int(value) if value else None


def _blob(html: str) -> str:
    return _tag(html)[2]


def _post(client, blob: str, handler: str = "", path: str = "/") -> dict:
    r = client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": path, "handler": handler, "data": {}, "snapshot": blob}
        ),
        headers=_MSGPACK,
    )
    assert r.status_code == 200, r.content
    return msgpack.unpackb(r.content, raw=False)


def _region_html(payload: dict) -> str:
    return "".join(entry["html"] for entry in payload.get("regions", []))


def test_refresh_shows_another_users_write(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project)) as c:
        alice = _blob(c.get("/").text)
        bob = _blob(c.get("/").text)

        _post(c, alice, handler="vote")

        # Bob's handler-less refresh (and any event of his) shows the vote.
        payload = _post(c, bob)
        assert "Votes: 1" in _region_html(payload)
        assert payload["live_every"] == 5000


def test_event_reply_also_refreshes_shared_regions(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project)) as c:
        alice = _blob(c.get("/").text)
        bob = _blob(c.get("/").text)
        _post(c, alice, handler="vote")

        html = _region_html(_post(c, bob, handler="bump"))
        assert "Votes: 1" in html
        assert "Mine: 1" in html


def test_unchanged_shared_region_is_not_resent(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project)) as c:
        first = _post(c, _blob(c.get("/").text))
        # No digest in the page-load snapshot: the first refresh sends it once.
        assert "Votes: 0" in _region_html(first)

        second = _post(c, first["snapshot"])
        assert second["regions"] == []

        alice = _blob(c.get("/").text)
        _post(c, alice, handler="vote")
        third = _post(c, second["snapshot"])
        assert "Votes: 1" in _region_html(third)


def test_page_without_shared_state_never_polls(project):
    _write(
        project,
        "index.wire",
        "---\ncount = wire(0)\n---\n<p>{count}</p>\n",
    )
    with TestClient(_app(project)) as c:
        html = c.get("/").text
        assert _live_every(html) is None
        assert _post(c, _blob(html))["live_every"] == 0


@pytest.mark.parametrize(
    ("expr", "shared"),
    [
        ("live_shared.votes.value", True),
        ("live_shared.doubled.value", True),
        ("live_shared.ticker.value", True),
        ("local_doubled.value", False),
        ("shared_doubled.value", True),
    ],
)
def test_what_counts_as_shared_state(project, expr, shared):
    _write(
        project,
        "index.wire",
        "---\n"
        "import live_shared\n"
        "count = wire(1)\n"
        "local_doubled = derived(lambda: count.value * 2)\n"
        "shared_doubled = derived(lambda: live_shared.votes.value * 2)\n"
        "---\n"
        f"<p>{{{expr}}}</p>\n",
    )
    with TestClient(_app(project)) as c:
        assert (_live_every(c.get("/").text) == 5000) is shared


def test_shared_state_in_a_layout_refreshes_the_page(project):
    _write(
        project,
        "__layout__.wire",
        "---\nimport live_shared\n---\n"
        "<html><body><nav>Votes: {live_shared.votes.value}</nav>"
        "<main>{$render children}</main></body></html>\n",
    )
    _write(project, "index.wire", "<p>home</p>\n")
    with TestClient(_app(project)) as c:
        html = c.get("/").text
        assert _live_every(html) == 5000
        import live_shared

        live_shared.votes.value = 3
        payload = _post(c, _blob(html))
        assert "Votes: 3" in payload.get("html", "") + _region_html(payload)


def test_live_directive_overrides_the_app_setting(project):
    _write(project, "fast.wire", VOTES_PAGE.format(directive="!live 500ms\n"))
    _write(project, "off.wire", VOTES_PAGE.format(directive="!live off\n"))
    with TestClient(_app(project)) as c:
        assert _live_every(c.get("/fast").text) == 500
        assert _live_every(c.get("/off").text) is None


def test_live_every_zero_turns_polling_off(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project, live_every=0)) as c:
        assert _live_every(c.get("/").text) is None


@pytest.mark.parametrize("seconds", [-1, 0.05])
def test_live_every_below_100ms_rejected(project, seconds):
    with pytest.raises(ValueError, match="live_every"):
        _app(project, live_every=seconds)


def test_dev_errors_when_no_interval_is_set(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    app = _app(project, live_every=None, debug=True)
    app._is_dev_mode = True
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/")
        assert r.status_code == 500
        assert "live_shared.votes" in r.text
        assert "live_every" in r.text


def test_dev_error_names_the_value(project):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    app = _app(project, live_every=None)
    app._is_dev_mode = True
    with TestClient(app) as c:
        with pytest.raises(PyWireSyntaxError, match=r"shows live_shared\.votes"):
            c.get("/")


def test_production_warns_once_and_does_not_poll(project, caplog):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project, live_every=None)) as c:
        with caplog.at_level("WARNING"):
            assert _live_every(c.get("/").text) is None
            c.get("/")
    warnings = [r for r in caplog.records if "live_every" in r.getMessage()]
    assert len(warnings) == 1


def test_writing_shared_state_warns_once(project, caplog):
    _write(project, "index.wire", VOTES_PAGE.format(directive=""))
    with TestClient(_app(project)) as c:
        blob = _blob(c.get("/").text)
        with caplog.at_level("WARNING"):
            blob = _post(c, blob, handler="vote")["snapshot"]
            _post(c, blob, handler="vote")
    warnings = [r for r in caplog.records if "wrote shared state" in r.getMessage()]
    assert len(warnings) == 1


def test_aliased_module_wire_stays_out_of_the_snapshot(project):
    # `votes = live_shared.votes` puts the module wire on the page. Restoring
    # it from a snapshot would roll every user back to that client's value.
    _write(
        project,
        "index.wire",
        "---\n"
        "import live_shared\n"
        "votes = live_shared.votes\n\n"
        "def vote():\n"
        "    votes.value += 1\n"
        "---\n"
        "<p>{votes}</p><button @click={vote}>vote</button>\n",
    )
    with TestClient(_app(project)) as c:
        stale = _blob(c.get("/").text)
        assert "votes" not in decode_snapshot(stale, secret=SECRET.encode())["attrs"]

        blob = stale
        for _ in range(3):
            blob = _post(c, blob, handler="vote")["snapshot"]
        import live_shared

        assert live_shared.votes.value == 3
        _post(c, stale)
        assert live_shared.votes.value == 3
