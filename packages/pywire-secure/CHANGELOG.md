# Changelog

All notable changes to `pywire-secure` are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and uses [release-please](https://github.com/googleapis/release-please) for automated releases.

Initial release: CSRF protection (stateless HMAC tokens auto-injected into POST forms), security headers middleware (X-Frame-Options, Referrer-Policy, Permissions-Policy on by default; HSTS and CSP opt-in via `CSPBuilder`), HTTPS-redirect wrapper, and an optional slowapi-backed rate limit adapter.

## Unreleased

_Release PR tracked by release-please._
