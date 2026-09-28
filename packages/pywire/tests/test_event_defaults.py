"""``PyWire(event_defaults=...)`` reaches the client through the page meta."""

import json
import re

import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire


def _meta(html: str) -> dict:
    m = re.search(r'<script id="_pywire_spa_meta"[^>]*>([^<]+)</script>', html)
    assert m, "no _pywire_spa_meta in the page"
    return json.loads(m.group(1))


def _app(tmp_path, **kwargs) -> PyWire:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.wire").write_text("<p>hi</p>\n")
    return PyWire(pages_dir=str(pages), **kwargs)


def test_defaults_reach_the_page_meta(tmp_path):
    app = _app(tmp_path, event_defaults={"input": "debounce.400ms", "keyup": "immediate"})
    with TestClient(app) as client:
        meta = _meta(client.get("/").text)
    assert meta["event_defaults"] == {"input": "debounce.400ms", "keyup": "immediate"}


def test_no_overrides_by_default(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert _meta(client.get("/").text)["event_defaults"] == {}


@pytest.mark.parametrize(
    "defaults",
    [{"input": "debounce 400"}, {"input": "slow"}, {"Input!": "immediate"}, {"x": 5}],
)
def test_bad_timing_is_refused(tmp_path, defaults):
    with pytest.raises(ValueError, match="event_defaults"):
        _app(tmp_path, event_defaults=defaults)
