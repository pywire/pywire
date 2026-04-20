---
title: OIDC Providers
description: Google, GitHub, Microsoft, Facebook, Auth0, Generic OIDC — setup and claim shapes.
---

`pywire-auth` ships six external-provider classes. All register via `connect_auth(app, providers=[...])`; the routes `GET /auth/{name}/login` and `GET /auth/{name}/callback` are mounted automatically. Callbacks round-trip through your session store and upsert users into the `auth_store` if one is configured.

## Common shape

```python
from pywire_auth import GoogleProvider, connect_auth

connect_auth(
    app,
    providers=[
        GoogleProvider(
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        ),
    ],
)
```

Callback URL to register with each provider's console:

```
https://yourapp.com/auth/{provider_name}/callback
```

where `{provider_name}` is `google`, `github`, `microsoft`, `facebook`, `auth0`, or whatever `name=` you set on a `GenericOIDCProvider`.

## Google

- **Console**: <https://console.cloud.google.com/apis/credentials>
- Create: OAuth 2.0 Client ID → Web application
- Redirect URI: `https://<host>/auth/google/callback`
- Scopes: `openid email profile` (default)
- Claims returned: `sub`, `email`, `email_verified`, `name`, `picture`, optional `hd` for Workspace accounts

```python
GoogleProvider(client_id=..., client_secret=...)
```

## GitHub

OAuth2, no id_token. `sub` is derived from GitHub's numeric `id`.

- **Console**: <https://github.com/settings/developers> → OAuth Apps → New
- Authorization callback URL: `https://<host>/auth/github/callback`
- Scopes: `read:user user:email` (default)
- Claims: `sub` (from `id`), `login`, `name`, `email`, `picture` (from `avatar_url`)

```python
GitHubProvider(client_id=..., client_secret=...)
```

## Microsoft / Azure AD

- **Console**: <https://portal.azure.com> → Azure Active Directory → App registrations → New
- Redirect URI: `https://<host>/auth/microsoft/callback`
- Tenant: `common` (default — multi-tenant + personal), a specific GUID, or `organizations`
- Create a client secret under **Certificates & secrets** — use the _Value_ column
- Claims: `sub`, `email`, `tid` (tenant id), `oid` (object id)

```python
MicrosoftProvider(
    client_id=..., client_secret=..., tenant="common",
)
```

## Facebook

OAuth2, no id_token.

- **Console**: <https://developers.facebook.com/apps>
- Add "Facebook Login" product → Valid OAuth Redirect URIs: `https://<host>/auth/facebook/callback`
- Scopes: `email public_profile` (default)
- Claims: `sub` (from `id`), `name`, `email` (only when user granted it), `picture` (unwrapped from nested `data.url`)

```python
FacebookProvider(client_id=..., client_secret=...)
```

## Auth0

Extends `GenericOIDCProvider`, derives discovery URL from the tenant domain.

- **Console**: <https://manage.auth0.com> → Applications → Create Application → Regular Web App
- Allowed Callback URLs: `https://<host>/auth/auth0/callback`
- Claims: `sub`, `email`, `name`, `picture`, plus anything your Auth0 Rules / Actions add (e.g. `role`)

```python
Auth0Provider(
    client_id=..., client_secret=..., domain="mytenant.us.auth0.com",
)
```

## Generic OIDC

Any IdP publishing `/.well-known/openid-configuration` works — Keycloak, Okta, Cognito, Zitadel, Logto, Google (if you want to exercise the generic path against real infra), etc.

```python
GenericOIDCProvider(
    name="keycloak",
    client_id=..., client_secret=...,
    discovery_url="https://auth.example.com/realms/demo/.well-known/openid-configuration",
)
```

`name=` becomes the URL segment: `/auth/keycloak/login`.

### Keycloak in a docker one-liner

For local testing without a cloud account:

```sh
docker run -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.0 start-dev
```

Then in the Keycloak admin console: create realm `demo`, client `pywire-demo` (Client authentication: on), redirect URI `http://localhost:3000/auth/keycloak/callback`. Point `discovery_url` at `http://localhost:8080/realms/demo/.well-known/openid-configuration`.

## Claim ownership: what lives where

Identity claims (`sub`, `email`, `email_verified`, `name`, `picture`) are owned by the IdP. They refresh on every login via the id_token or userinfo endpoint — if a user updates their Google name, the next login reflects it.

Authorization claims (`role`, `tier`, tenant membership, feature flags) live in **your** `auth_store`. They're added via `app.state.auth.grant(...)` and merged over the IdP's identity claims on every callback — so `role=admin` survives logout/login, across providers.

Never store authorization claims on the IdP. If you can't delete an admin claim without editing the IdP's config, you've coupled your access control to someone else's product.

## Env-gating providers

Register only the providers whose secrets are configured:

```python
providers = []
if all(os.environ.get(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")):
    providers.append(GoogleProvider(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    ))
```

The provider list is readable at `app.state.auth_providers` (list of names) — use it in your login page to render one "Sign in with X" button per configured IdP:

```pywire
---
from pywire import app
---
<div>
    <a $for={name in app.state.auth_providers}
       href={f"/auth/{name}/login?next=/profile"}>
        Sign in with {name}
    </a>
</div>
```
