# pywire-secure

CSRF protection, security headers, rate limiting, and HTTPS redirect for PyWire apps.

## Install

```sh
pip install pywire-secure
# Optional rate limiting:
pip install pywire-secure[ratelimit]
```

## Quick start

```python
from pywire import PyWire
from pywire_secure import connect_secure

app = PyWire(...)
connect_secure(app)
```

By default this enables:

- CSRF protection on all non-GET requests (auto-injects hidden `_csrf_token` field into every POST form)
- Safe security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`

Off by default — enable explicitly:

```python
connect_secure(
    app,
    https_redirect=True,
    rate_limit=True,
    hsts=True,
    csp="default-src 'self'",
)
```

## CSRF token in templates

The token is auto-injected into every `<form method="post">`. To use it manually (e.g. AJAX):

```html
<input type="hidden" name="_csrf_token" value={csrf_token}>
```

JS clients can read `window.__PYWIRE_CSRF_TOKEN__` or the `<meta name="pywire-csrf-token">` tag and send it via the `X-CSRF-Token` header.

## Per-page opt-out

Rare. Set in the page's Python section:

```python
__csrf_required__ = False
```

A `!no_csrf` directive will land in v0.2.

## Configuration via environment

| Variable | Default | Effect |
|---|---|---|
| `PYWIRE_SESSION_SECRET` | — | HMAC secret for token signing. Required when `csrf=True`. Reused from PyWire's session secret. |
| `PYWIRE_SECURE_CSRF` | `true` | Disable CSRF entirely. |
| `PYWIRE_SECURE_HEADERS` | `true` | Disable headers entirely. |
| `PYWIRE_SECURE_HTTPS_REDIRECT` | `false` | Force HTTPS. |
| `PYWIRE_SECURE_HSTS` | `false` | Add HSTS header. |
