---
title: Live Auth Updates
description: AuthActions, AuthChannel, and how a claim change reaches every live tab without a reload.
---

When an admin grants a role or revokes a session, every tab that user has open should react immediately — not on their next reload. PyWire's auth stack makes that a one-line call.

## The three layers

A claim change touches three stores with different lifetimes:

| Layer                   | Lifetime                  | What it does                                                   |
| ----------------------- | ------------------------- | -------------------------------------------------------------- |
| **`AuthStore`** row     | permanent                 | Survives logout/login. The canonical user record.              |
| **Sessions**            | per-login                 | Survive hard reloads. One per browser the user signed in with. |
| **`AuthChannel` event** | memory, per-WS-connection | Fans out to every live tab for this user_id.                   |

Any single-layer write is wrong:

- Only store → needs a sign-in again to reflect.
- Only the current session → the user's other browsers and devices keep the old claims.
- Only channel → in-memory; next request reads stale session.

`AuthActions` writes all three.

## `AuthActions` API

Constructed by `connect_auth` and exposed at `app.state.auth`. Every method acts on the user whose principal you pass, whoever is calling: a settings page passes `self.user`, an admin page passes the principal of the user it manages (for local users, `await idp.principal_for_user(user_id)`).

```python
# Page handler, inside a .wire script block
async def grant_admin():
    await app.state.auth.grant(self.user, "role", "admin")

async def revoke_admin():
    await app.state.auth.revoke_claim(self.user, "role")

async def update_claims():
    await app.state.auth.update_claims(
        self.user,
        [Claim(type="role", value="admin"), Claim(type="tier", value="beta")],
    )

async def sign_out_everywhere():
    await app.state.auth.revoke_sessions(self.user)
```

`grant` is sugar over `update_claims` for the common "add one claim" case. `revoke_claim` drops every claim of a given type. `revoke_sessions` signs the user out of every session they have and fires a channel revoke: live tabs navigate away now, and every other browser's next request is anonymous, landing on the guard's redirect.

Sessions pick the change up on their next request: `connect_auth` keeps a small per-user record in the session store saying when the user's claims last changed and when their sessions were last revoked, and `AuthMiddleware` brings each older session up to date. The record is keyed by the principal's `user_id` (`<provider>:<id>`).

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
    await app.state.auth.grant(self.user, "role", "admin")

async def revoke_admin():
    await app.state.auth.revoke_claim(self.user, "role")

async def sign_out_everywhere():
    await app.state.auth.revoke_sessions(self.user)
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
    <button @click={sign_out_everywhere()}>Sign out everywhere</button>
</div>
```

Open the page in two tabs. Click "Grant admin" in one — both tabs' admin region flips to visible instantly. Click "Sign out everywhere" — both tabs redirect to login, and so does any other browser on its next request.

## Cross-worker deployments

The default `MemoryAuthChannel` is in-process: its events only reach tabs connected to the worker that sent them. pywire-auth doesn't ship a cross-process channel. With several workers:

- Claim changes and `revoke_sessions` still reach every session on its next request, as long as the session store is shared (e.g. `RedisSessionStore`): the per-user record lives there.
- Live tabs connected to other workers only update on their next request or reconnect. To push to them too, pass your own `auth_channel=` implementing the `AuthChannel` protocol (`update_principal`, `revoke`, `subscribe`) over your pub/sub of choice.

## Channel semantics

| Event                               | What it means                            | Triggered by                                       |
| ----------------------------------- | ---------------------------------------- | -------------------------------------------------- |
| `kind="update"` + `principal=<new>` | Replace the principal                    | `channel.update_principal(user_id, principal=...)` |
| `kind="update"` + `claims=[...]`    | Overlay just claims on current principal | `channel.update_principal(user_id, claims=...)`    |
| `kind="revoke"`                     | Drop to `ANONYMOUS` + navigate           | `channel.revoke(user_id)`                          |

Events are best-effort: if the subscription task crashes or the WS closes the message is dropped. Design around that — use the channel for "refresh now" triggers, not for reliable state delivery. Authoritative state is always in the `auth_store`.
