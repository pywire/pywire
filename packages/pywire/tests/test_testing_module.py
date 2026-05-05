"""End-to-end tests for ``pywire.testing``.

These exercise the public API end to end: compiling a temp app from
inline source, driving HTTP requests, firing events, mocking auth,
selecting elements, and rendering pages/components in isolation.
"""

from __future__ import annotations

import pytest

from pywire.testing import (
    EventResult,
    make_principal,
    render_component,
    render_page,
    wire_page,
)


COUNTER_PAGE = """---
from pywire import wire

count = wire(0)

async def increment():
    count.value += 1
---
<h1 id="title">Count: {count}</h1>
<button @click={increment}>Inc</button>
"""

FORM_PAGE = """---
async def handle_submit(data):
    pass
---
<p>Form Page</p>
<form method="post" @submit={handle_submit}>
    <input name="name" />
    <button type="submit">Save</button>
</form>
"""

LAYOUT_PAGE = """<h1 class="title">Welcome</h1>
<p class="lede">Hello world</p>
<ul>
    <li>One</li>
    <li>Two</li>
</ul>
"""


# --- wire_page + basic GET ---


def test_wire_page_get_returns_rendered_html() -> None:
    with wire_page(COUNTER_PAGE) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Count: 0" in response.text


def test_wire_page_multi_route() -> None:
    with wire_page({"/": LAYOUT_PAGE, "/form": FORM_PAGE}) as client:
        assert "Welcome" in client.get("/").text
        assert "Form Page" in client.get("/form").text


def test_wire_page_cleans_up_tempdir() -> None:
    """No exceptions, no leftover state — same wire_page invocation
    twice in a row should each get a fresh app."""
    with wire_page(COUNTER_PAGE) as c1:
        assert c1.get("/").status_code == 200
    with wire_page(COUNTER_PAGE) as c2:
        assert c2.get("/").status_code == 200


# --- submit_form ---


def test_submit_form_posts_with_handler_header() -> None:
    with wire_page(FORM_PAGE, interactive_server_mode=False) as client:
        response = client.submit_form(
            "/", handler="handle_submit", data={"name": "alice"}
        )
        assert response.status_code == 200


def test_submit_form_missing_handler_returns_400() -> None:
    """No handler header == loud failure — proves the helper is the
    minimum-viable shape, not silently optional."""
    with wire_page(FORM_PAGE, interactive_server_mode=False) as client:
        response = client.post("/", data={"name": "alice"})
        assert response.status_code == 400


# --- force_login / logout ---


def test_force_login_replaces_get_user() -> None:
    with wire_page(COUNTER_PAGE) as client:
        principal = make_principal(name="alice")
        client.force_login(principal)
        assert client.app.get_user(None) is principal  # type: ignore[arg-type]


class _StubRequest:
    """Minimal stand-in for the request shape ``app.get_user`` walks."""

    scope: dict = {}


def test_logout_restores_original_behavior() -> None:
    """After logout, get_user no longer returns the forced principal."""
    with wire_page(COUNTER_PAGE) as client:
        principal = make_principal(name="alice")
        client.force_login(principal)
        assert client.app.get_user(_StubRequest()) is principal
        client.logout()
        # The original get_user falls back to scope — no forced principal anymore.
        assert client.app.get_user(_StubRequest()) is not principal


def test_force_login_restored_on_context_exit() -> None:
    """Even if the test forgets to call logout(), exit must restore."""
    captured_app = None
    with wire_page(COUNTER_PAGE) as client:
        captured_app = client.app
        principal = make_principal(name="alice")
        client.force_login(principal)
        assert captured_app.get_user(_StubRequest()) is principal
    assert captured_app is not None
    assert captured_app.get_user(_StubRequest()) is not principal


# --- fire_event + EventResult ---


@pytest.mark.asyncio
async def test_fire_event_invokes_handler_and_returns_result() -> None:
    with wire_page(COUNTER_PAGE) as client:
        result = await client.fire_event("/", handler="increment")
        assert isinstance(result, EventResult)
        assert result.update_type in {"regions", "full"}


@pytest.mark.asyncio
async def test_fire_event_unknown_path_raises_lookup() -> None:
    with wire_page(COUNTER_PAGE) as client:
        with pytest.raises(LookupError):
            await client.fire_event("/does-not-exist", handler="increment")


def test_event_result_region_html_lookup() -> None:
    payload = {
        "type": "regions",
        "regions": [
            {"region": "main", "html": "<p>hi</p>"},
            {"region": "footer", "html": "<p>bye</p>"},
        ],
        "commands": [],
        "meta": {"page_interactive": True},
    }
    result = EventResult.from_dict(payload)
    assert result.region_html("main") == "<p>hi</p>"
    assert result.region_html("missing") is None
    assert result.meta == {"page_interactive": True}
    assert result.raw is payload


# --- select() ---


def test_select_returns_lxml_elements() -> None:
    with wire_page(LAYOUT_PAGE) as client:
        response = client.get("/")
        titles = client.select(response, "h1.title")
        assert len(titles) == 1
        assert titles[0].text_content().strip() == "Welcome"


def test_select_multiple_matches() -> None:
    with wire_page(LAYOUT_PAGE) as client:
        response = client.get("/")
        items = client.select(response, "li")
        assert [el.text_content() for el in items] == ["One", "Two"]


def test_select_no_matches_returns_empty_list() -> None:
    with wire_page(LAYOUT_PAGE) as client:
        response = client.get("/")
        assert client.select(response, ".does-not-exist") == []


# --- session() ---


def test_session_context_reads_writes_dict() -> None:
    with wire_page(FORM_PAGE, interactive_server_mode=False) as client:
        # Make a request so the session cookie is minted.
        client.get("/")
        with client.session() as data:
            data["custom"] = "value"
        with client.session() as data:
            assert data.get("custom") == "value"


def test_session_without_cookie_raises() -> None:
    with wire_page(COUNTER_PAGE, interactive_server_mode=False) as client:
        with pytest.raises(RuntimeError, match="No pywire_session cookie"):
            with client.session():
                pass


# --- render_page ---


@pytest.mark.asyncio
async def test_render_page_returns_html_directly() -> None:
    with wire_page(LAYOUT_PAGE) as client:
        html = await render_page(client.app, "/")
        assert '<h1 class="title">Welcome</h1>' in html


@pytest.mark.asyncio
async def test_render_page_unknown_path_raises() -> None:
    with wire_page(LAYOUT_PAGE) as client:
        with pytest.raises(LookupError):
            await render_page(client.app, "/missing")


@pytest.mark.asyncio
async def test_render_page_with_user() -> None:
    """Pass a principal directly — no force_login needed."""
    with wire_page(LAYOUT_PAGE) as client:
        admin = make_principal(name="admin", claims=[("role", "admin")])
        html = await render_page(client.app, "/", user=admin)
        assert "Welcome" in html


# --- render_component ---


@pytest.mark.asyncio
async def test_render_component_standalone() -> None:
    """A compiled .wire page class can be rendered directly as a component
    via :func:`render_component` — no HTTP, no app, no parent page."""
    with wire_page(LAYOUT_PAGE) as client:
        match = client.app.router.match("/")
        assert match is not None
        page_class = match[0]
        html = await render_component(page_class)
        assert "Welcome" in html


# --- make_principal ---


def test_make_principal_defaults() -> None:
    p = make_principal()
    assert p.is_authenticated is True
    assert p.name == "test-user"
    assert p.user_id == "test-user-id"
    assert p.claims == []


def test_make_principal_with_claims_tuples() -> None:
    p = make_principal(name="alice", claims=[("role", "admin"), ("dept", "eng")])
    assert p.name == "alice"
    types = [c.type for c in p.claims]
    assert types == ["role", "dept"]


def test_make_principal_anonymous() -> None:
    p = make_principal(is_authenticated=False)
    assert p.is_authenticated is False
