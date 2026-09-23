"""Tests for HTML CSRF token injection.

These tests pin the regex behaviour around the rough edges of real-world
markup: multi-line form attributes, forms inside ``<script>``-typed
template blocks, opt-out via ``data-pywire-no-csrf``, malformed input
without ``<head>`` / ``<body>``, and attribute-escaping the token value.
"""

from __future__ import annotations

import pytest

from pywire_secure.injection import inject_csrf_tokens

TOKEN = "1700000000:" + "a" * 32


def test_basic_injection_full_document() -> None:
    html = "<html><head><title>x</title></head><body><form method='post'></form></body></html>"
    out = inject_csrf_tokens(html, TOKEN)
    assert '<meta name="pywire-csrf-token"' in out
    assert "window.__PYWIRE_CSRF_TOKEN__" in out
    assert '<input type="hidden" name="_csrf_token"' in out
    assert out.index("pywire-csrf-token") < out.index("</head>")


def test_token_value_appears_in_all_three_sites() -> None:
    out = inject_csrf_tokens(
        "<html><head></head><body><form></form></body></html>", TOKEN
    )
    assert out.count(TOKEN) == 3


def test_form_with_method_post() -> None:
    html = '<form method="post"></form>'
    assert "_csrf_token" in inject_csrf_tokens(html, TOKEN)


def test_form_without_attributes_still_gets_injection() -> None:
    """v0.1 strategy: inject into every <form> regardless of method.
    The form may carry @submit (PyWire event handler) which auto-becomes
    a POST at submit time — safer to over-inject than miss."""
    html = "<form><input></form>"
    assert "_csrf_token" in inject_csrf_tokens(html, TOKEN)


def test_data_pywire_no_csrf_skips_injection_no_value() -> None:
    html = "<form data-pywire-no-csrf method='post'></form>"
    assert "_csrf_token" not in inject_csrf_tokens(html, TOKEN)


def test_data_pywire_no_csrf_skips_injection_with_value() -> None:
    html = '<form data-pywire-no-csrf="" method="post"></form>'
    assert "_csrf_token" not in inject_csrf_tokens(html, TOKEN)


def test_mixed_forms_inject_only_protected_ones() -> None:
    html = (
        "<form id='a' method='post'></form>"
        "<form id='b' data-pywire-no-csrf method='post'></form>"
        "<form id='c' method='post'></form>"
    )
    out = inject_csrf_tokens(html, TOKEN)
    assert out.count("_csrf_token") == 2


def test_multiline_form_attributes() -> None:
    html = """<form
        method="post"
        action="/x"
    >content</form>"""
    out = inject_csrf_tokens(html, TOKEN)
    assert '<input type="hidden" name="_csrf_token"' in out


def test_form_inside_raw_text_template_skipped() -> None:
    """A literal `<form>` inside <script type="text/template"> is markup
    in a string, not a real form — must not be injected into."""
    html = '<script type="text/template"><form method="post"></form></script>'
    assert "_csrf_token" not in inject_csrf_tokens(html, TOKEN)


def test_form_inside_style_block_skipped() -> None:
    html = "<style>/* <form></form> */</style><form method='post'></form>"
    out = inject_csrf_tokens(html, TOKEN)
    # Only the real form gets the hidden input.
    assert out.count("_csrf_token") == 1


def test_no_head_falls_back_to_body() -> None:
    html = "<body><form></form></body>"
    out = inject_csrf_tokens(html, TOKEN)
    assert "pywire-csrf-token" in out
    assert out.index("pywire-csrf-token") < out.index("<form")


def test_no_head_no_body_prepends() -> None:
    html = "<form></form>"
    out = inject_csrf_tokens(html, TOKEN)
    assert out.startswith('<meta name="pywire-csrf-token"')


def test_meta_inserted_before_existing_head_close() -> None:
    html = "<head><title>x</title></head><body></body>"
    out = inject_csrf_tokens(html, TOKEN)
    assert out.index("pywire-csrf-token") < out.index("</head>")


def test_token_attribute_escaped() -> None:
    """A pathological token containing an HTML metacharacter must not
    break out of the attribute value. Real CSRF tokens never contain
    these chars but a custom strategy might emit them, and an unescaped
    injection would be an XSS sink."""
    out = inject_csrf_tokens("<head></head><body><form></form></body>", 'a"<script>')
    assert "<script>" not in out.replace(
        "<script>window.__PYWIRE_CSRF_TOKEN__", ""
    )  # the literal payload is never present unescaped
    assert "&quot;" in out
    assert "&lt;script&gt;" in out


def test_empty_token_is_noop() -> None:
    html = "<head></head><body><form></form></body>"
    assert inject_csrf_tokens(html, "") == html


def test_self_closing_input_inside_form_unaffected() -> None:
    html = '<form method="post"><input type="text" name="x" /></form>'
    out = inject_csrf_tokens(html, TOKEN)
    assert out.count("_csrf_token") == 1


@pytest.mark.parametrize(
    "html",
    [
        "<form>a</form><form>b</form>",
        "<form>a</form>\n<form>b</form>",
        "<form>a</form><div><form>b</form></div>",
    ],
)
def test_multiple_forms_each_get_token(html: str) -> None:
    out = inject_csrf_tokens(html, TOKEN)
    assert out.count("_csrf_token") == 2
