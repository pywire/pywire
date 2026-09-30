---
title: Authentication
description: Principals, claims, policies, and guards in PyWire.
---

PyWire's auth stack is a separate package — `pywire-auth` — that layers on top of the core framework. The core ships the primitives (`ClaimsPrincipal`, `PolicyEngine`, `!auth` and `{$auth}` directives); `pywire-auth` wires up providers, session handling, stores, and the live-auth channel.

```sh
pip install pywire-auth
```

Optional extras:

- `pywire-auth[sqlalchemy]` — persistent user store (see [Local IdP & Persistence](./authentication/local-idp/))

## Mental model

Three things travel together:

1. **Principal** — a `ClaimsPrincipal` attached to `self.user` on every page. Carries `is_authenticated`, `user_id`, `name`, a list of `Claim(type, value)` entries, and the raw provider payload.
2. **Policy engine** — named policies registered at boot via `engine.add_policy("Name", requires_claim=("role", "admin"))` or with an arbitrary async callable. Evaluated server-side.
3. **Guards** — the `!auth` page-level directive and the `{$auth}` region-level directive both call into the engine to decide what renders.

Claims are authoritative on the server. The client sees HTML the server decided to render; it never gets to argue.

## Wire-up in one call

```python
from pywire import PyWire
from pywire_auth import (
    GoogleProvider,
    LocalIdP,
    SQLAlchemyAuthStore,
    connect_auth,
)

app = PyWire(pages_dir="src/pages")
store = SQLAlchemyAuthStore("sqlite+aiosqlite:///./auth.db")

engine = connect_auth(
    app,
    providers=[GoogleProvider(client_id=..., client_secret=...)],
    local_idp=LocalIdP(store=store),
)
engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
```

`connect_auth` takes care of:

- Mounting `/auth/{provider}/login` + `/auth/{provider}/callback` for every OIDC provider in the list
- Mounting `/auth/local/{register,login,token,verify-token,revoke}` when `local_idp=` is passed
- Installing `AuthMiddleware` (populates `scope["user"]` + `scope["pywire_session_id"]` on every request)
- Installing `SessionMiddleware` if the app doesn't already have one (interactive-mode PyWire apps skip it by default)
- Exposing `app.state.auth` (an `AuthActions` helper), `app.state.auth_store`, `app.state.local_idp`, `app.state.auth_providers`, and `app.state.auth_channel`

## Protecting a whole page

Use the page-level `!auth` directive at the top of the script section:

```pywire
!auth {"policy": "AdminOnly", "redirect": "/login_local"}

---
from pywire import app
---

<h1>Admin dashboard</h1>
<p>User: {user.name}</p>
```

If the guard denies, the page renders a 303 redirect to `redirect` (defaults to `/login`) and no `@before_load` / `@init` hooks run. User code is never reached on denial.

Shorthand forms:

```pywire
!auth
!auth "AdminOnly"
!auth {"claims": [["role", "admin"], ["email_verified", "true"]]}
```

## Protecting a region within a page

`{$auth}` gates a region in-place — no redirect, just branch rendering:

```pywire
{$auth policy="AdminOnly"}
    <p>Admin-only panel.</p>
{$else}
    <p>Request access from an admin.</p>
{/auth}
```

Claim check form:

```pywire
{$auth claims=[("role", "admin"), ("tier", "beta")]}
    <p>Beta admin features.</p>
{/auth}
```

Async form with an explicit "authorizing" state and a bound boolean:

```pywire
{$auth policy="AdminOnly"}
    <small>Checking permissions…</small>
{$then allowed}
    {$if allowed}
        <p>Unlocked.</p>
    {$else}
        <p>Locked.</p>
    {/if}
{/auth}
```

Each `{$auth}` region is evaluated independently, works inside `{$for}`, updates live via the `AuthChannel`, and fails closed when a policy is missing or raises.

## Reading the principal

From a page's script block:

```pywire
---
def greet():
    if self.user.is_authenticated:
        return f"Hello, {self.user.name}"
    return "Hello, guest"
---
<h1>{greet()}</h1>
<p $if={user.has_claim("role", "admin")}>Admin link →</p>
```

`self.user` is always a `ClaimsPrincipal` — anonymous requests get `ANONYMOUS` (the frozen sentinel), never `None`. `has_claim(type, value=None)` returns `True` for any matching type when `value` is `None`.

## Mutating claims at runtime

`app.state.auth` (an `AuthActions` helper) bundles three writes — the persistent user row, every session the user is signed in with, and a live fan-out event — into one call. It acts on the user you pass, so an admin page can manage other users the same way:

```python
await app.state.auth.grant(user, "role", "admin")
await app.state.auth.revoke_claim(user, "role")
await app.state.auth.revoke_sessions(user)  # sign out everywhere
```

Changes persist across hard reloads and survive logout/login. Every tab the user has open re-renders immediately. See [Live Auth Updates](./authentication/live-auth/).

## Session security

`connect_auth` takes care of the usual session attacks:

- Signing in or out moves the session to a new id, so an id planted in a browser before login is useless after it.
- The session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` on requests that arrived over HTTPS. Behind a proxy that terminates TLS, run the server with forwarded headers trusted (`uvicorn --proxy-headers`) or pass `connect_auth(..., cookie_secure=True)`.
- `next=` and `error_next=` only redirect to a path on your own site (`/dashboard`), never to another host.
- Logout is `POST` only, and the login, register and logout routes refuse cross-site requests.
- OAuth logins use PKCE, require a signed `id_token` with the login's `nonce` from OIDC providers, and build callback URLs from `connect_auth(..., base_url="https://app.example.com")` when you pass it (otherwise from the request's Host header).

## Where to go next

- **[OIDC Providers](./authentication/providers/)** — Google, GitHub, Microsoft, Facebook, Auth0, Generic OIDC setup
- **[Local IdP & Persistence](./authentication/local-idp/)** — Username/password login, SQLite/Postgres storage, first-time DB setup
- **[Live Auth Updates](./authentication/live-auth/)** — `AuthActions`, `AuthChannel`, the WebSocket subscription
