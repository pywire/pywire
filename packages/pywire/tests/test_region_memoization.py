"""Phase 10: output-equality skip for ``render_update``.

Verifies that a dirty region producing the same HTML as the previous
render does not get emitted as a morphdom patch, while a real change
does. Avoids wasted wire traffic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from pywire.runtime.page import BasePage


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
        "http_version": "1.1",
    }
    return Request(scope)


class _FakePage(BasePage):
    """A page with a single region renderer we can drive manually."""

    __region_renderers__ = {"r_test": "_render_region_r_test"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._render_counter = 0
        self._next_html = "<div>a</div>"

    async def _render_region_r_test(self) -> str:
        self._render_counter += 1
        return self._next_html


@pytest.mark.asyncio
async def test_render_update_skips_unchanged_region():
    page = _FakePage(_make_request(), {}, {})
    # Prime the cache with a first render.
    page._dirty_regions.add("r_test")
    first = await page.render_update(init=False)
    assert first["type"] == "regions"
    assert len(first["regions"]) == 1
    assert first["regions"][0]["html"] == "<div>a</div>"

    # Mark dirty again without changing the output.
    page._dirty_regions.add("r_test")
    second = await page.render_update(init=False)
    assert second["type"] == "regions"
    # Skip fired: no patches emitted for the unchanged region.
    assert second["regions"] == []


@pytest.mark.asyncio
async def test_render_update_emits_on_real_change():
    page = _FakePage(_make_request(), {}, {})
    page._dirty_regions.add("r_test")
    await page.render_update(init=False)

    page._next_html = "<div>b</div>"
    page._dirty_regions.add("r_test")
    out = await page.render_update(init=False)
    assert out["type"] == "regions"
    assert len(out["regions"]) == 1
    assert out["regions"][0]["html"] == "<div>b</div>"


@pytest.mark.asyncio
async def test_clear_wire_tracking_drops_output_cache():
    page = _FakePage(_make_request(), {}, {})
    page._dirty_regions.add("r_test")
    await page.render_update(init=False)
    assert page._region_output_cache.get("r_test") == "<div>a</div>"

    page._clear_wire_tracking()
    assert page._region_output_cache == {}
