# Changelog

All notable changes to `pywire-auth` are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and uses [release-please](https://github.com/googleapis/release-please) for automated releases.

Initial release: batteries-included authentication — OAuth2/OIDC providers (Google, GitHub, Microsoft, Facebook, Auth0, generic OIDC), a local identity provider with Argon2 password hashing, a `SQLAlchemyAuthStore` for cross-restart persistence, policy engine with claim-based guards, `AuthActions` bundling store/session/channel mutations into one call, and a live auth channel that pushes claim changes to logged-in tabs without reload.

## Unreleased
