"""Inline handler arguments that read `event` are evaluated when the event fires."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pywire.runtime.loader import PageLoader

PAGE = """
---
search_query = wire("")
rows = wire([{"id": 1}, {"id": 2}])
renamed = []

def on_search(value):
    search_query.value = value

def rename(row_id, value):
    renamed.append((row_id, value))
---
<input @input={on_search(event.value)}>
<input @input={on_search($event.value)}>
{$for row in rows}<input @input={rename(row["id"], event.value)}>{/for}
"""


@pytest.fixture
def page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "page.wire").write_text(PAGE)
    monkeypatch.chdir(tmp_path)
    page_class = PageLoader().load(tmp_path / "page.wire")
    request = MagicMock()
    return page_class(request, {}, {}, {}, None)


@pytest.mark.asyncio
async def test_event_argument_is_not_evaluated_at_render(page) -> None:
    response = await page.render(init=True)
    inputs = re.findall(r"<input[^>]*>", response.body.decode())

    assert len(inputs) == 4
    # `event.value` is read in the handler, so the client only sends `value`.
    assert all('data-pw-fields-input="value"' in tag for tag in inputs)
    # Render-time names in the same call are still lifted per row.
    assert 'data-arg-0="1"' in inputs[2] and 'data-arg-0="2"' in inputs[3]


@pytest.mark.asyncio
async def test_event_argument_reads_the_fired_event(page) -> None:
    await page.render(init=True)

    await page.handle_event("_handler_0", {"type": "input", "value": "hello"})
    assert page.search_query.peek() == "hello"

    await page.handle_event("_handler_1", {"type": "input", "value": "alias"})
    assert page.search_query.peek() == "alias"

    await page.handle_event(
        "_handler_2", {"type": "input", "value": "x", "args": {"arg-0": 2}}
    )
    assert page.renamed == [(2, "x")]
