"""A wire written inside a component nested in another component re-renders
the page: the write reaches every ancestor, and each component's memo also
watches its children's wires."""

import asyncio
import sys

from starlette.requests import Request

from pywire.runtime.loader import PageLoader

_SCOPE = {
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


def test_nested_component_event_updates_the_page(tmp_path, monkeypatch):
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "nest_inner.wire").write_text(
        "---\ncount = wire(0)\ndef bump():\n    count.value += 1\n---\n"
        "<button @click={bump}>+</button><p>C={count}</p>\n"
    )
    (tmp_path / "nest_outer.wire").write_text(
        "---\nfrom nest_inner import NestInner\n---\n<section><NestInner /></section>\n"
    )
    page_file = tmp_path / "page.wire"
    page_file.write_text("---\nfrom nest_outer import NestOuter\n---\n<NestOuter />\n")
    try:
        cls = PageLoader().load(page_file, use_cache=False)
        page = cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})
        html = asyncio.run(page.render()).body.decode()
        assert "C=0" in html
        outer = next(iter(page._components.values()))
        inner_key = next(iter(outer._components))
        handler = f"_comp:{outer._component_key}:_comp:{inner_key}:bump"
        update = asyncio.run(page.handle_event(handler, {"type": "click"}))
        assert "C=1" in str(update)
    finally:
        sys.modules.pop("nest_inner", None)
        sys.modules.pop("nest_outer", None)
