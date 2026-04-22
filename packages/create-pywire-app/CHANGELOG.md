# Changelog

## [0.10.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.9.0...create-pywire-app-v0.10.0) (2026-04-22)


### Features

* split pywire CLI, add pywire check static analysis, oneliner scaffolder ([#156](https://github.com/pywire/pywire/issues/156)) ([d2b8a9d](https://github.com/pywire/pywire/commit/d2b8a9dff0871ff1d9b4cabc64a855842c48fbb6))

## [0.9.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.8.0...create-pywire-app-v0.9.0) (2026-04-20)


### Features

* render regions (snippets, $render, $head) — retire slots ([#127](https://github.com/pywire/pywire/issues/127)) ([d2b48b6](https://github.com/pywire/pywire/commit/d2b48b635a4263b1568b0302e09875a5557c8004))

## [0.8.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.7.0...create-pywire-app-v0.8.0) (2026-04-18)


### Features

* **pywire:** pre-warm CF Durable Object during HTTP request ([72673a2](https://github.com/pywire/pywire/commit/72673a26ac1fb3a8874aa9439feb7ea5537ff08a))


### Bug Fixes

* **create-pywire-app:** sync CF templates with pywire deploy ([9787dcf](https://github.com/pywire/pywire/commit/9787dcf7c4f2a794b2377a7dd742329fb6a864bf))

## [0.7.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.6.0...create-pywire-app-v0.7.0) (2026-04-15)


### Features

* **pywire:** make pydantic optional, fix CF Workers cold start and deployment ([b891602](https://github.com/pywire/pywire/commit/b891602f92fd7bedee721884e5eaf8cd14dd81c2))

## [0.6.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.5.1...create-pywire-app-v0.6.0) (2026-04-15)


### Features

* **pywire:** improve deploy CLI platform UX ([2aa64ec](https://github.com/pywire/pywire/commit/2aa64ec9b33260495fd073d709ad6ba70b01a399))


### Bug Fixes

* **create-pywire-app:** add railway link step before railway up ([78b1393](https://github.com/pywire/pywire/commit/78b13936bf730985a203b32f1fe7b1611b93468e))

## [0.5.1](https://github.com/pywire/pywire/compare/create-pywire-app-v0.5.0...create-pywire-app-v0.5.1) (2026-04-15)


### Bug Fixes

* **create-pywire-app:** pass workers to pyproject.toml template context ([17ad3f7](https://github.com/pywire/pywire/commit/17ad3f74241c6bcef0c501a8b269f7028f780dd1))

## [0.5.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.4.0...create-pywire-app-v0.5.0) (2026-04-15)


### Features

* Cloudflare Python Workers support ([#110](https://github.com/pywire/pywire/issues/110)) ([9866d10](https://github.com/pywire/pywire/commit/9866d1096b31cf34758d33b8728ae318b0bc1566))

## [0.4.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.3.0...create-pywire-app-v0.4.0) (2026-04-13)


### Features

* **pywire:** reconnect overlay, lifecycle hooks, typed refs, dispatch, media refs ([#85](https://github.com/pywire/pywire/issues/85)) ([9a8b43d](https://github.com/pywire/pywire/commit/9a8b43d4868e9a2149f85f597112275ea5425c7b))
* stores, middleware, context API, deploy CLI, event optimization, and cache busting ([#43](https://github.com/pywire/pywire/issues/43)) ([00e55d1](https://github.com/pywire/pywire/commit/00e55d18a177a9cdb1378eaede2969f30b91f9ff))


### Bug Fixes

* adapt internal references for monorepo layout ([a260035](https://github.com/pywire/pywire/commit/a26003572b9ae460ce36f3e4a5e41881ad7115a4))
* **create-pywire-app:** multi-deployment README only showed first adapter ([1f32d46](https://github.com/pywire/pywire/commit/1f32d46d44815032cc312d8c76d9e7da251ebcd9))
* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
* **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## [0.3.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.2.0...create-pywire-app-v0.3.0) (2026-04-13)


### Features

* **pywire:** reconnect overlay, lifecycle hooks, typed refs, dispatch, media refs ([#85](https://github.com/pywire/pywire/issues/85)) ([9a8b43d](https://github.com/pywire/pywire/commit/9a8b43d4868e9a2149f85f597112275ea5425c7b))


### Bug Fixes

* **create-pywire-app:** multi-deployment README only showed first adapter ([1f32d46](https://github.com/pywire/pywire/commit/1f32d46d44815032cc312d8c76d9e7da251ebcd9))

## [0.2.0](https://github.com/pywire/pywire/compare/create-pywire-app-v0.1.7...create-pywire-app-v0.2.0) (2026-04-10)


### Features

* stores, middleware, context API, deploy CLI, event optimization, and cache busting ([#43](https://github.com/pywire/pywire/issues/43)) ([00e55d1](https://github.com/pywire/pywire/commit/00e55d18a177a9cdb1378eaede2969f30b91f9ff))

## [0.1.7](https://github.com/pywire/pywire/compare/create-pywire-app-v0.1.6...create-pywire-app-v0.1.7) (2026-04-07)


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))
* **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## [0.1.6](https://github.com/pywire/pywire/compare/create-pywire-app-v0.1.5...create-pywire-app-v0.1.6) (2026-04-07)


### Bug Fixes

* adapt internal references for monorepo layout ([a260035](https://github.com/pywire/pywire/commit/a26003572b9ae460ce36f3e4a5e41881ad7115a4))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
