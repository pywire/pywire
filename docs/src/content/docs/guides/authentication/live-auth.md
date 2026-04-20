---
title: Live Auth Updates
description: AuthActions, AuthChannel, and how a claim change reaches every live tab without a reload.
---

When an admin grants a role or revokes a session, every tab that user has open should react immediately — not on their next reload. PyWire's auth stack makes that a one-line call.

## The three layers

A claim change touches three stores with different lifetimes:

| Layer                   | Lifetime                  | What it does                                           |
| ----------------------- | ------------------------- | ------------------------------------------------------ |
| **`AuthStore`** row     | permanent                 | Survives logout/login. The canonical user record.      |
| **Session snapshot**    | per-login                 | Survives hard reloads. Written by `SessionMiddleware`. |
| **`AuthChannel` event** | memory, per-WS-connection | Fans out to every live tab for this user_id.           |

Any single-layer write is wrong:

- Only store → needs a reload to reflect.
- Only session → wiped on logout.
- Only channel → in-memory; next request reads stale session.

`AuthActions` writes all three in order.

## `AuthActions` API

Constructed by `connect_auth` and exposed at `app.state.auth`. All methods take the current `principal` and `request` so the helper can locate the right session id:

```python
# Page handler, inside a .wire script block
async def grant_admin():
    await app.state.auth.grant(self.user, self.request, "role", "admin")

async def revoke_admin():
    await app.state.auth.revoke_claim(self.user, self.request, "role")

async def update_claims():
    await app.state.auth.update_claims(
        self.user, self.request,
        [Claim(type="role", value="admin"), Claim(type="tier", value="beta")],
    )

async def revoke_session():
    await app.state.auth.revoke_session(self.user, self.request)
```

`grant` is sugar over `update_claims` for the common "add one claim" case. `revoke_claim` drops every claim of a given type. `revoke_session` clears the session's auth key and fires a channel revoke — the next request lands on the guard's redirect.

## How the live push works

1. WebSocket connects. If the principal is authenticated, the handler calls `channel.subscribe(user_id)` and spawns a task that awaits events.
2. A handler somewhere calls `app.state.auth.grant(...)`. Third step fires `channel.update_principal(user_id, principal=new)`.
3. The subscription task receives an `AuthEvent(kind="update")`. It rewrites `page.user` in place, marks the root scope dirty, and calls the page's `_on_update` broadcaster.
4. Next `render_update` is a full re-render. Every expression reading `self.user` (direct, `has_claim`, `{$auth}` region evaluation) sees the new principal.
5. If the updated principal fails the page-level `!auth` guard (common after a revoke), the handler pushes a `navigate` message and ends the subscription. Client goes to `/login_local` (or wherever `redirect=` points).

All without a reload.

## Putting it together

A demo page that toggles the current user's admin claim live:

```pywire
!auth {"redirect": "/login_local"}

---
from pywire import app

async def grant_admin():
    await app.state.auth.grant(self.user, self.request, "role", "admin")

async def revoke_admin():
    await app.state.auth.revoke_claim(self.user, self.request, "role")

async def revoke_session():
    await app.state.auth.revoke_session(self.user, self.request)
---

<h1>Live auth</h1>

<p>Current claims: {[(c.type, c.value) for c in user.claims]}</p>

{$auth policy="AdminOnly"}
    <p>🔓 Admin content visible.</p>
{$else}
    <p>🔒 Admin content hidden.</p>
{/auth}

<div>
    <button @click={grant_admin()}>Grant admin</button>
    <button @click={revoke_admin()}>Revoke admin</button>
    <button @click={revoke_session()}>Sign out</button>
</div>
```

Open the page in two tabs. Click "Grant admin" in one — both tabs' admin region flips to visible instantly. Click "Sign out" — both tabs redirect to login.

## Cross-worker deployments

The default `MemoryAuthChannel` is in-process. Fine for single-worker (which PyWire's dev server and small prod deployments typically are), but if you run multiple uvicorn/hypercorn workers behind a load balancer the channel event only reaches workers holding the connection. Swap in the Redis-backed channel once it ships:

```python
from pywire_auth import RedisAuthChannel  # coming

connect_auth(app, auth_channel=RedisAuthChannel(url=os.environ["REDIS_URL"]))
```

Same interface; events fan out via Redis pub/sub.

## Channel semantics

| Event                               | What it means                            | Triggered by                                       |
| ----------------------------------- | ---------------------------------------- | -------------------------------------------------- |
| `kind="update"` + `principal=<new>` | Replace the principal                    | `channel.update_principal(user_id, principal=...)` |
| `kind="update"` + `claims=[...]`    | Overlay just claims on current principal | `channel.update_principal(user_id, claims=...)`    |
| `kind="revoke"`                     | Drop to `ANONYMOUS` + navigate           | `channel.revoke(user_id)`                          |

Events are best-effort: if the subscription task crashes or the WS closes the message is dropped. Design around that — use the channel for "refresh now" triggers, not for reliable state delivery. Authoritative state is always in the `auth_store`.
