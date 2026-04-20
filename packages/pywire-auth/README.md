# pywire-auth

Authentication for [PyWire](https://pywire.dev). OAuth2 / OIDC providers, a local identity provider with Argon2 password hashing, session-backed principals, policies, and a live-update channel so logged-in tabs react to claim changes without a reload.

## Install

```sh
pip install pywire-auth
```

Optional extras:

- `pywire-auth[sqlalchemy]` — persistent `SQLAlchemyAuthStore` for the local IdP (SQLite / Postgres / MySQL / any async SQLA driver; ships `aiosqlite` for the default SQLite URL)
- `pywire-auth[redis]` — cross-worker `RedisAuthChannel` (coming)

Providers ship as config-only extras; the HTTP layer is `httpx` + `authlib` which are always installed:

- `pywire-auth[google]` `pywire-auth[github]` `pywire-auth[microsoft]` `pywire-auth[facebook]` `pywire-auth[auth0]` — declarative today, provider-specific deps land here later without a compat break

## Quick start

```python
# src/main.py
import os
from pathlib import Path
from pywire import PyWire
from pywire_auth import (
    GoogleProvider,
    GitHubProvider,
    LocalIdP,
    SQLAlchemyAuthStore,
    connect_auth,
)

app = PyWire(pages_dir=str(Path(__file__).parent / "pages"))

# Local password auth, persisted to SQLite by default. Override via
# LOCAL_AUTH_DB env var for Postgres / etc.
store = SQLAlchemyAuthStore(
    os.environ.get("LOCAL_AUTH_DB", "sqlite+aiosqlite:///./local-auth.db")
)

providers = []
if os.environ.get("GOOGLE_CLIENT_ID"):
    providers.append(GoogleProvider(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    ))
if os.environ.get("GITHUB_CLIENT_ID"):
    providers.append(GitHubProvider(
        client_id=os.environ["GITHUB_CLIENT_ID"],
        client_secret=os.environ["GITHUB_CLIENT_SECRET"],
    ))

engine = connect_auth(
    app,
    providers=providers,
    local_idp=LocalIdP(store=store),  # reads LOCAL_IDP_SECRET from env
)
engine.add_policy("AdminOnly", requires_claim=("role", "admin"))
```

`connect_auth` mounts:

- `GET /auth/{provider}/login` + `GET /auth/{provider}/callback` — one pair per OIDC provider in the list
- `POST /auth/local/{register,login,token,verify-token,revoke}` — only when `local_idp=...` is passed
- `GET /auth/logout` — clears session + fires an `AuthChannel.revoke`

and exposes the `AuthActions` helper at `app.state.auth` for one-call claim mutations.

## Protecting pages

Page-level (hard redirect):

```wire
!auth {"policy": "AdminOnly"}

<h1>Admin dashboard</h1>
```

Region-level (renders an "allowed" or "denied" branch in place):

```wire
{$auth policy="AdminOnly"}
    <p>Admin-only content</p>
{$else}
    <p>Contact an administrator.</p>
{/auth}
```

Both check the principal against the named policy or the inline `claims=[...]` list. Policies fail closed — unknown policies, missing engine, and user-code exceptions all deny.

## LocalIdP persistence

In-memory default is fine for unit tests. For any real dev loop, wire a SQLite file:

```python
from pywire_auth import LocalIdP, SQLAlchemyAuthStore

store = SQLAlchemyAuthStore("sqlite+aiosqlite:///./local-auth.db")
idp = LocalIdP(store=store)  # secret from LOCAL_IDP_SECRET env
```

Schema (three tables — `pywire_auth_users`, `pywire_auth_credentials`, `pywire_auth_provider_links`) auto-initializes on first query. For Postgres, `postgresql+asyncpg://user:pw@host/db`; for MySQL, `mysql+aiomysql://...`. The `metadata` object is importable for Alembic:

```python
from pywire_auth.stores.sqlalchemy import metadata
```

See the [Local IdP setup guide](https://pywire.dev/guides/authentication/local-idp/) for first-time setup + production tips.

## Live auth

`AuthActions` writes claim changes to all three layers in one call:

```python
# In a page handler
await app.state.auth.grant(self.user, self.request, "role", "admin")
await app.state.auth.revoke_claim(self.user, self.request, "role")
await app.state.auth.revoke_session(self.user, self.request)
```

Store → session → `AuthChannel` in that order: the change persists across logins, survives a hard reload, and re-renders every connected tab for that user without a page refresh.

## Providers

| Provider | Shape | Notes |
|---|---|---|
| `GoogleProvider` | OIDC | Fixed endpoints; returns `sub`, `email`, `email_verified`, `name`, `picture`, optional `hd` |
| `GitHubProvider` | OAuth2 | No id_token; `sub` derived from `id`, `login` returned |
| `MicrosoftProvider` | OIDC | `tenant="common"` default; per-tenant via GUID/domain |
| `FacebookProvider` | OAuth2 | v18.0 endpoints; unwraps nested `picture.data.url` |
| `Auth0Provider` | OIDC | Pass `domain=<tenant>.auth0.com`; extends `GenericOIDCProvider` |
| `GenericOIDCProvider` | OIDC | Any `/.well-known/openid-configuration`; works for Keycloak / Okta / Cognito / Zitadel / Logto |

All providers accept `client_id` + `client_secret` and expose `authorize_url` / `exchange_code` / `refresh` / `map_claims`.

## API reference

Full reference at [pywire.dev/reference/auth-api](https://pywire.dev/reference/auth-api/).

## License

MIT
