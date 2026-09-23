import asyncio

import pytest
from starlette.requests import Request

from pywire.runtime.loader import PageLoader

WIRE = """---
count = wire(0)

def increment():
    count.value += 1
---
<p>{count}</p>
<button @click={increment()}>go</button>
"""


def _page(tmp_path):
    f = tmp_path / "allowlist.wire"
    f.write_text(WIRE)
    cls = PageLoader().load(f, use_cache=False)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"localhost")],
        "scheme": "http",
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 1),
    }
    return cls(request=Request(scope), params={}, query={}, path={"main": True})


def test_allowlist_contains_user_handlers(tmp_path):
    allowed = type(_page(tmp_path)).__event_handlers__
    assert allowed is not None and "increment" in allowed


@pytest.mark.parametrize(
    "name", ["attrs", "render", "__init__", "navigate", "push_state"]
)
def test_dispatch_rejects_non_handlers(tmp_path, name):
    with pytest.raises(ValueError):
        asyncio.run(_page(tmp_path)._dispatch_handler(name, {}))


def test_dispatch_allows_listed_handler(tmp_path):
    page = _page(tmp_path)
    asyncio.run(page._dispatch_handler("increment", {}))
    assert page.count.value == 1
