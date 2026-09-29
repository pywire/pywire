"""Codegen tests for `.optimistic` / `.optimistic-class-*` event modifiers.

These are presentation-only predictions declared in `.wire`, compiled to the
existing `data-modifiers-*` channel and applied by the client. This module
locks the compile side: the generic modifier pass-through must emit them and
reject a malformed `optimistic-class-` token with an empty name.
"""

import ast
from textwrap import dedent

import pytest

from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.compiler.parser import PyWireParser

FIXTURE = dedent(
    """\
    ---
    async def h(event):
        pass
    ---
    <button {attr}>Go</button>
    """
)


def _render_code_gen(attr: str) -> str:
    parsed = PyWireParser().parse(FIXTURE.format(attr=attr))
    return ast.unparse(CodeGenerator().generate(parsed))


def _modifiers_line(code: str) -> str:
    return next(
        line for line in code.splitlines() if "data-modifiers-click" in line
    )


def test_optimistic_modifier_emits_data_attribute() -> None:
    code = _render_code_gen("@click.optimistic={h}")
    assert "'data-modifiers-click'] = 'optimistic'" in code


def test_optimistic_class_token_emitted() -> None:
    code = _render_code_gen("@click.optimistic-class-done={h}")
    assert "'data-modifiers-click'] = 'optimistic-class-done'" in code


def test_multiple_optimistic_class_tokens_emitted() -> None:
    code = _render_code_gen(
        "@click.optimistic-class-done.optimistic-class-dim={h}"
    )
    assert (
        "'data-modifiers-click'] = 'optimistic-class-done optimistic-class-dim'"
        in code
    )


def test_prevent_and_optimistic_combined() -> None:
    code = _render_code_gen("@click.prevent.optimistic={h}")
    assert "'data-modifiers-click'] = 'prevent optimistic'" in code


def test_empty_optimistic_class_token_rejected() -> None:
    with pytest.raises(PyWireSyntaxError):
        PyWireParser().parse(FIXTURE.format(attr="@click.optimistic-class-={h}"))
