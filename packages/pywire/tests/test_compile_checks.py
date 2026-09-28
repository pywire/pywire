"""Compile-time checks for frontmatter names (#295) and $-boolean attributes (#294)."""

from pathlib import Path

import pytest
from pywire.compiler.exceptions import PyWireSyntaxError
from pywire.runtime.loader import PageLoader


@pytest.mark.parametrize(
    "frontmatter",
    [
        'query = wire("")',
        "params: dict = {}",
        "def request():\n    return 1",
        "async def url():\n    return 1",
        "path, other = 1, 2",
    ],
)
def test_reserved_name_is_a_compile_error(tmp_path: Path, frontmatter: str) -> None:
    page = tmp_path / "page.wire"
    page.write_text(f"---\n{frontmatter}\n---\n<p>hi</p>\n")

    with pytest.raises(PyWireSyntaxError, match="reserved page attribute") as exc:
        PageLoader().load(page)
    assert exc.value.line == 2


def test_reading_reserved_names_still_compiles(tmp_path: Path) -> None:
    page = tmp_path / "page.wire"
    page.write_text(
        "---\nsearch = wire('')\n\ndef term():\n    return query.get('q', '')\n---\n"
        "<p>{search} {term}</p>\n"
    )

    PageLoader().load(page)


@pytest.mark.parametrize(
    "markup",
    [
        "<button $disabled={count > 1}>a</button>",
        '<input type="checkbox" $checked={count} />',
        "<div><input $readonly /></div>",
    ],
)
def test_dollar_boolean_attribute_is_a_compile_error(
    tmp_path: Path, markup: str
) -> None:
    # Regression for #294: `$checked` / `$disabled` were documented but
    # rendered literally (`$checked=""`), which broke DOM diffing.
    page = tmp_path / "page.wire"
    page.write_text(f"---\ncount = wire(0)\n---\n{markup}\n")

    with pytest.raises(PyWireSyntaxError, match="not a pywire directive") as exc:
        PageLoader().load(page)
    assert exc.value.line == 4


@pytest.mark.asyncio
async def test_plain_boolean_attribute_toggles(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    page = tmp_path / "page.wire"
    page.write_text(
        "---\ncount = wire(10)\n---\n"
        "<button disabled={count >= 10}>a</button>"
        '<input type="checkbox" checked={count < 10} />\n'
    )
    request = MagicMock()
    request.app.state.webtransport_cert_hash = None
    request.app.state.enable_pjax = False
    request.app.state.interactive_server_mode = True
    html = await PageLoader().load(page)(request, {}, {}, {}, None)._render_template()

    assert 'disabled=""' in html
    assert "checked" not in html


def _page(tmp_path: Path, source: str):
    from unittest.mock import MagicMock

    page_file = tmp_path / "page.wire"
    page_file.write_text(source)
    request = MagicMock()
    request.app.state.webtransport_cert_hash = None
    request.app.state.enable_pjax = False
    request.app.state.interactive_server_mode = True
    return PageLoader().load(page_file)(request, {}, {}, {}, None)


def test_comprehension_variable_does_not_shadow_handler_param(tmp_path: Path) -> None:
    # Regression for #280: `for i in range(...)` leaked into page state as
    # self.i and the handler's `i` read the leftover 999.
    page = _page(
        tmp_path,
        """---
items = wire([{"done": False} for i in range(10)])
label = wire("page")

def toggle(i):
    items[i]["done"] = not items[i]["done"]

def echo(label):
    return label
---
<p>{items}</p>
""",
    )
    assert not hasattr(page, "i")

    page.toggle(5)

    assert [k for k, row in enumerate(page.items) if row["done"]] == [5]
    # A parameter named like a page variable is the parameter.
    assert page.echo("arg") == "arg"
