"""Codegen tests for the ``@poll`` directive.

``@poll`` compiles to ``data-pw-poll="{handler}"`` (plus ``data-pw-poll-every``
for a non-default interval) instead of the generic ``data-on-poll`` event
channel — ``poll`` is not a DOM event and must never become a
``addEventListener('poll', …)`` target. The handler is allowlisted through the
same ``_process_handlers`` pass as ``@click``, so both the stateless POST
dispatch and the WebSocket dispatch accept it.
"""

import ast
import asyncio
import sys
from textwrap import dedent

import pytest
from starlette.requests import Request

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.compiler.parser import PyWireParser
from pywire.runtime.loader import PageLoader

FIXTURE = dedent(
    """\
    ---
    count = wire(0)

    def tick():
        count.value += 1
    ---
    <button {attr}>Tick</button>
    """
)

_ARG_FIXTURE = dedent(
    """\
    ---
    items = wire([1, 2, 3])
    seen = wire([])

    def tick(idx):
        seen.value = seen.value + [idx]
    ---
    <div $for={item in items}>
        <button @poll.every-400={tick(item)}>Tick {item}</button>
    </div>
    """
)

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


def _render_code_gen(attr: str) -> str:
    parsed = PyWireParser().parse(FIXTURE.format(attr=attr))
    return ast.unparse(CodeGenerator().generate(parsed))


def _page(tmp_path, attr: str = "@poll.every-400={tick()}"):
    f = tmp_path / "poll.wire"
    f.write_text(FIXTURE.format(attr=attr))
    cls = PageLoader().load(f, use_cache=False)
    return cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})


def test_poll_emits_data_pw_poll_and_every() -> None:
    code = _render_code_gen("@poll.every-400={tick()}")
    assert "'data-pw-poll'] =" in code
    assert "'data-pw-poll-every'] = '400'" in code


def test_poll_default_emits_no_every() -> None:
    code = _render_code_gen("@poll={tick()}")
    assert "'data-pw-poll'] =" in code
    assert "data-pw-poll-every" not in code


def test_poll_is_not_wired_as_dom_listener() -> None:
    code = _render_code_gen("@poll.every-400={tick()}")
    assert "data-on-poll" not in code
    assert "data-modifiers-poll" not in code


def test_poll_every_below_100_fails_at_compile() -> None:
    with pytest.raises(PyWireSyntaxError):
        _render_code_gen("@poll.every-50={tick()}")


def test_poll_handler_is_allowlisted(tmp_path) -> None:
    page = _page(tmp_path)
    allowed = type(page).__event_handlers__
    assert allowed is not None
    # @poll={tick()} wraps into an inline _handler_N like any inline event
    # handler; that wrapper name is what data-pw-poll points at and must be
    # dispatchable (stateless POST + WS both route through _dispatch_handler).
    assert "_handler_0" in allowed
    asyncio.run(page._dispatch_handler("_handler_0", {}))
    assert page.count.value == 1


def test_poll_lifts_args_as_data_arg() -> None:
    """@poll={tick(item)} inside $for emits data-arg-0 like @click does."""
    parsed = PyWireParser().parse(_ARG_FIXTURE)
    code = ast.unparse(CodeGenerator().generate(parsed))
    assert "'data-arg-0'] =" in code
    assert "'data-pw-poll'] =" in code
    assert "'data-pw-poll-every'] = '400'" in code
    # poll dispatch relies on __event_handlers__, not ref dispatch()
    # interception — no _register_handler is (or should be) emitted.
    assert "_register_handler" not in code


def test_poll_arg_reaches_handler(tmp_path) -> None:
    """The lifted arg is delivered to the poll handler on dispatch."""
    f = tmp_path / "poll_arg.wire"
    f.write_text(_ARG_FIXTURE)
    cls = PageLoader().load(f, use_cache=False)
    page = cls(request=Request(_SCOPE), params={}, query={}, path={"main": True})
    allowed = type(page).__event_handlers__
    assert allowed is not None and "_handler_0" in allowed
    # Client lifts data-arg-0 into args.arg0 exactly as poll.ts getArgs does.
    asyncio.run(page._dispatch_handler("_handler_0", {"args": {"arg0": 1}}))
    assert page.seen.value == [1]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
