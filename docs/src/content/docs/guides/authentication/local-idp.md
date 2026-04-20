---
title: Local IdP & Persistence
description: Username/password login with persistent user storage.
---

`LocalIdP` is the built-in password-based identity provider. It hashes passwords with Argon2, issues JWTs via an HS256 `TokenIssuer`, and stores users in a pluggable `AuthStore`. For real work you want persistence — the default `MemoryAuthStore` wipes everything on restart, fine for unit tests and not much else.

## Quick start

```sh
pip install 'pywire-auth[sqlalchemy]'
```

```python
# main.py
import os
from pywire import PyWire
from pywire_auth import LocalIdP, SQLAlchemyAuthStore, connect_auth

app = PyWire(pages_dir="src/pages")

store = SQLAlchemyAuthStore(
    os.environ.get("LOCAL_AUTH_DB", "sqlite+aiosqlite:///./local-auth.db")
)
idp = LocalIdP(store=store)  # reads LOCAL_IDP_SECRET from env

connect_auth(app, local_idp=idp)
```

```env
# .env
PYWIRE_SESSION_SECRET=<openssl rand -hex 32>
LOCAL_IDP_SECRET=<openssl rand -hex 32>
LOCAL_AUTH_DB=sqlite+aiosqlite:///./local-auth.db
```

`connect_auth(local_idp=idp)` mounts:

- `POST /auth/local/register` — email + password, writes principal + session
- `POST /auth/local/login` — verify, writes principal + session
- `POST /auth/local/token` — issue a short-lived JWT for the logged-in user
- `POST /auth/local/verify-token` — verify a JWT and return decoded claims
- `POST /auth/local/revoke` — clear session + fire `channel.revoke(user_id)`

On failure each route redirects to the `Referer` page with `?error=<code>` so your form page can display the message.

## Schema

Three tables auto-created on first query:

```
pywire_auth_users          user_id | email | name | claims (JSON) | extras (JSON)
pywire_auth_credentials    user_id | pw_hash
pywire_auth_provider_links provider | subject | user_id | claims (JSON)
```

`provider_links` stores both the LocalIdP link (provider=`local`, subject=email) and any OIDC provider links when a user signs in with Google / GitHub / etc. — the admin UI can show every account by querying this table.

Alembic users can import the `MetaData` directly:

```python
from pywire_auth.stores.sqlalchemy import metadata
# env.py
target_metadata = metadata
```

## Production backends

Any async SQLAlchemy driver works. Install the driver alongside `pywire-auth[sqlalchemy]`:

| Backend | URL | Driver |
|---|---|---|
| SQLite (default) | `sqlite+aiosqlite:///./local-auth.db` | `aiosqlite` (ships with the extra) |
| Postgres | `postgresql+asyncpg://user:pw@host/db` | `pip install asyncpg` |
| MySQL / MariaDB | `mysql+aiomysql://user:pw@host/db` | `pip install aiomysql` |
| SQL Server | `mssql+aioodbc://...` | `pip install aioodbc` |

Sharing one engine across the rest of your app? Pass the engine directly:

```python
from sqlalchemy.ext.asyncio import create_async_engine
engine = create_async_engine(os.environ["DATABASE_URL"])
store = SQLAlchemyAuthStore(engine)
```

`SQLAlchemyAuthStore` won't dispose the engine on `close()` when you bring your own.

## Login + register flow

```wire
<!-- src/pages/login_local.wire -->
---
error = self.query.get("error") if hasattr(self, "query") else None
---

<h1>Log in</h1>

<p $if={error == "invalid"}>Invalid email or password.</p>

<form method="POST" action="/auth/local/login">
    <input type="hidden" name="next" value="/profile" />
    <input type="email" name="email" required />
    <input type="password" name="password" required />
    <button type="submit">Log in</button>
</form>

<p>No account? <a href="/register">Register</a>.</p>
```

```wire
<!-- src/pages/register.wire -->
---
error = self.query.get("error") if hasattr(self, "query") else None
---

<h1>Register</h1>

<p $if={error == "exists"}>That email is already registered.</p>

<form method="POST" action="/auth/local/register">
    <input type="hidden" name="next" value="/profile" />
    <input type="email" name="email" required />
    <input type="password" name="password" required />
    <input type="text" name="name" placeholder="Display name" />
    <!-- Optional: grant an initial claim -->
    <input type="text" name="role" placeholder="admin / editor" />
    <input type="checkbox" name="email_verified" /> email_verified
    <button type="submit">Register</button>
</form>
```

Register accepts `email`, `password`, `name`, `role`, `email_verified` (checkbox) and any `next` / `error_next` redirect targets.

## First-time DB setup checklist

1. Install the extra: `pip install 'pywire-auth[sqlalchemy]'` (or use `uv` / `poetry`).
2. Set `PYWIRE_SESSION_SECRET` and `LOCAL_IDP_SECRET` in `.env` — each needs 32+ random chars (`openssl rand -hex 32`).
3. Point `LOCAL_AUTH_DB` at wherever you want the DB file (SQLite) or the connection URL (Postgres/MySQL). Defaults to `./local-auth.db`.
4. Construct `SQLAlchemyAuthStore(url)` + `LocalIdP(store=store)` + `connect_auth(app, local_idp=idp)`.
5. Boot: `uv run pywire dev`. Register via `/register`, log in via `/login_local`. The DB file appears on first query.
6. Done. Restarts preserve users. Back up the DB file the same way you'd back up any SQLite file.

## Token issuance

LocalIdP issues HS256 JWTs for logged-in local users:

```python
# Server-side
from pywire import app
idp = app.state.local_idp
token = idp.issue_id_token(user_id="<uuid>", claims={"role": "admin"}, ttl=600)
payload = idp.verify_id_token(token)
```

HTTP surface at `POST /auth/local/token` for the currently logged-in session (401 if anonymous) and `POST /auth/local/verify-token` with `{"token": "..."}` body. Returned JWT is signed with `LOCAL_IDP_SECRET` — the issuer string is `pywire-auth-local` by default (override via `LocalIdP(issuer="...")`).

Use this for machine-to-machine auth between trusted services, CLI-issued pre-auth links, short-lived invite tokens, etc. For cross-tenant federation, stand up a real IdP — this is not meant to be a full OAuth2 server.
