import asyncio
import sys

import pytest
from starlette.requests import Request

from pywire.runtime.loader import PageLoader

WIRE = """---
count = wire(0)

def increment():
    count.value += 1

def reset_everything():
    count.value = -1
---
<p>{count}</p>
<button @click={increment}>go</button>
<button @click={count += 1}>inline</button>
"""

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


def _page(tmp_path):
    f = tmp_path / "allowlist.wire"
    f.write_text(WIRE)
    cls = PageLoader().load(f, use_cache=False)
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


def test_allowlist_is_what_the_template_wires(tmp_path):
    # @click={increment} wires increment by name; the inline statement gets
    # a generated wrapper. reset_everything is wired nowhere.
    allowed = type(_page(tmp_path)).__event_handlers__
    assert allowed == frozenset({"increment", "_handler_0"})


@pytest.mark.parametrize(
    "name", ["attrs", "render", "__init__", "navigate", "push_state"]
)
def test_dispatch_rejects_non_handlers(tmp_path, name):
    with pytest.raises(ValueError):
        asyncio.run(_page(tmp_path)._dispatch_handler(name, {}))


def test_allowlist_is_only_what_the_template_binds(tmp_path):
    # ``reset_everything`` is a frontmatter def no template attribute binds:
    # plain Python the client must never reach by name.
    allowed = type(_page(tmp_path)).__event_handlers__
    assert allowed == frozenset({"increment", "_handler_0"})


def test_dispatch_rejects_unbound_frontmatter_function(tmp_path):
    page = _page(tmp_path)
    with pytest.raises(ValueError, match="not a registered event handler"):
        asyncio.run(page._dispatch_handler("reset_everything", {}))
    assert page.count.value == 0


def test_dispatch_allows_listed_handler(tmp_path):
    page = _page(tmp_path)
    asyncio.run(page._dispatch_handler("_handler_0", {}))
    assert page.count.value == 1


LIFTED = """---
balance = wire(100)
price = 5

def charge(amount):
    balance.value -= amount

def helper():
    balance.value = 0
---
<p>{balance}</p>
<button @click={charge(price)}>buy</button>
<button @click={helper}>reset</button>
"""


def test_defs_reached_only_through_a_wrapper_are_not_callable(tmp_path):
    """charge() is only reachable through its wrapper, which supplies the
    amount server-side: a client must not call it with its own."""
    f = tmp_path / "lifted.wire"
    f.write_text(LIFTED)
    cls = PageLoader().load(f, use_cache=False)
    assert cls.__event_handlers__ == frozenset({"_handler_0", "helper"})
    page = cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})
    with pytest.raises(ValueError, match="not a registered event handler"):
        asyncio.run(page._dispatch_handler("charge", {"args": {"amount": -5000}}))
    assert page.balance.value == 100
    asyncio.run(page._dispatch_handler("_handler_0", {}))
    assert page.balance.value == 95


def test_dispatch_ignores_unknown_name(tmp_path):
    # Stale DOM refs after hot reload: unresolvable names are a silent no-op,
    # unlike resolvable-but-unlisted names (ValueError above).
    page = _page(tmp_path)
    assert asyncio.run(page._dispatch_handler("nonexistent_xyz", {})) is None
    assert page.count.value == 0


HOOKS_WIRE = """---
from pywire import expose

n = wire(0)

def plain():
    n.value += 1

@init
def on_init():
    pass

@mount
def on_mount():
    pass

@unmount
def on_unmount():
    pass

@before_load
def on_before_load():
    pass

@before_update
def on_before_update():
    pass

@after_update
def on_after_update():
    pass

@after_update
def wired_hook():
    n.value += 10

@error
def on_error(exc):
    return False

@effect
def on_effect():
    n.value

@derived
def doubled():
    return n.value * 2

@expose
def exposed():
    n.value = 100
---
<button @click={plain}>{n}</button>
<button @click={wired_hook}>{doubled}</button>
"""

FRAMEWORK_INVOKED = [
    "on_init",
    "on_mount",
    "on_unmount",
    "on_before_load",
    "on_before_update",
    "on_after_update",
    "on_error",
    "on_effect",
    "doubled",
    "exposed",
]


def _hooks_page(tmp_path):
    (tmp_path / "hooks.wire").write_text(HOOKS_WIRE)
    cls = PageLoader().load(tmp_path / "hooks.wire", use_cache=False)
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


@pytest.mark.parametrize("name", FRAMEWORK_INVOKED)
def test_framework_invoked_defs_not_dispatchable(tmp_path, name):
    page = _hooks_page(tmp_path)
    assert name not in type(page).__event_handlers__
    with pytest.raises(ValueError):
        asyncio.run(page._dispatch_handler(name, {}))


def test_template_wired_defs_dispatchable(tmp_path):
    # A def the template names as a handler stays dispatchable even if it
    # also carries a hook decorator.
    page = _hooks_page(tmp_path)
    asyncio.run(page._dispatch_handler("plain", {}))
    asyncio.run(page._dispatch_handler("wired_hook", {}))
    assert page.n.value == 11


CHILD_WIRE = """---
from typing import Optional
from pywire import props, expose, EventHandler

@props
class Props:
    on_bump: Optional[EventHandler] = None

n = wire(0)

def bump():
    n.value += 1
    if on_bump:
        on_bump()

@expose
def reset():
    n.value = 0
---
<button @click={bump}>{n}</button>
"""

PARENT_WIRE = """---
from pywire import ref
from allowlist_child import AllowlistChild

total = wire(0)
child_ref = ref()

def on_child():
    total.value += 1
---
<AllowlistChild $ref={child_ref} @bump={on_child} />
<p>{total}</p>
"""


def test_component_dispatch_enforces_component_allowlist(tmp_path, monkeypatch):
    from pywire.runtime.importer import install_import_hook

    install_import_hook()
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "allowlist_child.wire").write_text(CHILD_WIRE)
    (tmp_path / "allowlist_parent.wire").write_text(PARENT_WIRE)
    try:
        cls = PageLoader().load(tmp_path / "allowlist_parent.wire", use_cache=False)
        page = cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})
        html = asyncio.run(page.render()).body.decode()
        key, child = next(iter(page._components.items()))
        event = f"_comp:{key}:bump"
        assert f'data-on-click="{event}"' in html

        # Child handler dispatches by name; its on_bump callback prop reaches
        # the parent's handler as a plain callable.
        asyncio.run(page.handle_event(event, {}))
        assert child.n.value == 1 and page.total.value == 1

        # @expose is reached server-side via the ref, never by client name.
        page.child_ref.reset()
        assert child.n.value == 0

        for bad in ["render", "attrs", "__init__", "reset"]:
            with pytest.raises(ValueError):
                asyncio.run(page.handle_event(f"_comp:{key}:{bad}", {}))
    finally:
        sys.modules.pop("allowlist_child", None)
