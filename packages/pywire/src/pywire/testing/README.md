# pywire.testing

Test helpers for PyWire apps — `.wire` page compilation, HTTP-level driving, direct event firing, auth mocking, CSS selection, and standalone component rendering.

## Install

```sh
pip install 'pywire[testing]'
```

This adds `httpx`, `lxml`, and `cssselect` as dev dependencies. Production wheels do not pull these in.

Importing `pywire.testing` without the extra raises `ImportError` with the install command.

## Quick start

```python
from pywire.testing import TestClient, wire_page, make_principal

# 1. Compile inline .wire source for a single test
with wire_page("""---
from pywire import wire

count = wire(0)

async def increment():
    count.value += 1
---
<h1>Count: {count}</h1>
<button @click={increment}>Inc</button>
""") as client:
    response = client.get("/")
    assert response.status_code == 200
    assert "Count: 0" in response.text
```

## API reference

### `wire_page(source, *, interactive_server_mode=True, route="/", **kwargs)`

Context manager. Compiles inline `.wire` source into a temp app and yields a `TestClient`. Pass a `dict[route, source]` for multi-page apps.

```python
with wire_page({"/": home_src, "/about": about_src}) as client:
    ...
```

The temp directory is cleaned up on exit. Each invocation gets a fresh `MemorySessionStore`.

### `TestClient(app, *, base_url="http://testserver", raise_server_exceptions=False)`

Composes `starlette.testclient.TestClient`. All HTTP methods (`get`, `post`, `put`, `patch`, `delete`, `request`, `websocket_connect`) proxy to the underlying client.

PyWire-specific methods:

#### `client.force_login(principal)` / `client.logout()`

Monkeypatches `app.get_user` so every request inside the client's lifetime sees `principal`. The original `get_user` is restored on `logout()` or context exit.

#### `client.submit_form(url, *, handler, data=None, files=None, spa=False, **kwargs)`

POSTs a form to a non-interactive page handler with the `X-PyWire-Handler` header pre-set. Pass `spa=True` for body-fragment SPA submits.

#### `await client.fire_event(url, *, handler, data=None, user=None)` → `EventResult`

Drives an event handler directly against a freshly resolved page — bypasses the WebSocket protocol for speed. Returns an `EventResult` with `.regions`, `.html`, `.commands`, `.meta`, `.raw`, plus a `region_html(region_id)` helper.

```python
result = await client.fire_event("/page", handler="increment")
assert "Count: 1" in result.region_html("counter")
```

#### `client.session()`

Context manager exposing the live session-store dict for the current cookie. Mutations are persisted on exit.

```python
client.get("/")  # mints the cookie
with client.session() as data:
    data["custom"] = "value"
```

Requires `interactive_server_mode=False` (the path that installs `SessionMiddleware`).

#### `client.select(response, css)`

Returns matched `lxml.html.HtmlElement` objects. Backed by `cssselect`.

```python
titles = client.select(response, "h1.title")
assert titles[0].text_content() == "Hello"
```

### `make_principal(*, name="test-user", user_id="test-user-id", is_authenticated=True, claims=None)`

Builds a `pywire.auth.ClaimsPrincipal`. `claims` accepts `(type, value)` tuples or pre-built `Claim` objects.

```python
admin = make_principal(name="alice", claims=[("role", "admin")])
client.force_login(admin)
```

### `await render_page(app, path, *, user=None)` → `str`

Resolves a path to a page and returns its rendered HTML — no HTTP, no middleware, no session. Fastest path for pure-render assertions.

### `await render_component(component_class, *, request=None, init=False, **props)` → `str`

Renders a component standalone. Props become instance attributes.

### `EventResult`

Wraps the dict returned by `BasePage.render_update`:

| Attribute | Type | Description |
|-----------|------|-------------|
| `update_type` | `str` | `"regions"` for partial, `"full"` for full re-render |
| `regions` | `list[dict]` | Partial update fragments (`{"region": str, "html": str}`) |
| `html` | `str \| None` | Full document HTML when `update_type == "full"` |
| `commands` | `list` | Client-side ops (set_cookie, navigate, etc.) |
| `meta` | `dict` | Update metadata (e.g. `page_interactive`) |
| `raw` | `dict` | The original payload — escape hatch for new keys |
| `.region_html(region_id)` | `str \| None` | Helper to look up one region's HTML |

## Patterns

**Per-test isolation**: every `wire_page` block creates a fresh tempdir, fresh `MemorySessionStore`, fresh `PyWire` instance. No cross-test state.

**Auth-gated routes**: combine `force_login` with `make_principal` — no session-cookie surgery needed.

```python
with wire_page(admin_only_page) as client:
    client.force_login(make_principal(claims=[("role", "admin")]))
    assert client.get("/admin").status_code == 200
```

**Event assertions**: `fire_event` returns the same payload the WS handler would emit, so assertions translate one-to-one between unit tests and integration tests.

## What's not in v0.1

- WebSocket transport via real `websocket_connect` + msgpack roundtrip — `fire_event` is the fast path; the underlying `client.websocket_connect()` is available if you need full protocol fidelity.
- `client.login(username, password)` against a real LocalIdP. Use `force_login` for now.
- HTML diff helpers / snapshot testing.
