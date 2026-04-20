# Changelog

## [0.1.1](https://github.com/pywire/pywire/compare/pywire-auth-v0.1.0...pywire-auth-v0.1.1) (2026-04-20)


### Bug Fixes

* **pywire-auth:** public-API docstring + add PyPI publish job ([620aa66](https://github.com/pywire/pywire/commit/620aa66523c9429e20948df94729fcba693fbcbc))

## [0.1.0](https://github.com/pywire/pywire/compare/pywire-auth-v0.1.0...pywire-auth-v0.1.0) (2026-04-20)


### Features

* **pywire-auth:** initial release — OIDC + LocalIdP + policies ([6a5af64](https://github.com/pywire/pywire/commit/6a5af6412a992dcfcaa062e6d26356bf0f087ce1))


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## Changelog

All notable changes to `pywire-auth` are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and uses [release-please](https://github.com/googleapis/release-please) for automated releases.

Initial release: batteries-included authentication — OAuth2/OIDC providers (Google, GitHub, Microsoft, Facebook, Auth0, generic OIDC), a local identity provider with Argon2 password hashing, a `SQLAlchemyAuthStore` for cross-restart persistence, policy engine with claim-based guards, `AuthActions` bundling store/session/channel mutations into one call, and a live auth channel that pushes claim changes to logged-in tabs without reload.

## Unreleased

_Release PR tracked by release-please._
