# Changelog

## [0.3.0](https://github.com/pywire/pywire/compare/pywire-docs-v0.2.0...pywire-docs-v0.3.0) (2026-04-10)


### Features

* stores, middleware, context API, deploy CLI, event optimization, and cache busting ([#43](https://github.com/pywire/pywire/issues/43)) ([00e55d1](https://github.com/pywire/pywire/commit/00e55d18a177a9cdb1378eaede2969f30b91f9ff))

## [0.2.0](https://github.com/pywire/pywire/compare/pywire-docs-v0.1.0...pywire-docs-v0.2.0) (2026-04-07)

### Features

- restructure monorepo, add CI/deploy workflows ([5127c56](https://github.com/pywire/pywire/commit/5127c56dd38542eda545b27693ec4b2e4b9e6152))

### Bug Fixes

- correct PYWIRE_PKG path in docs build-assets script ([ccd18c1](https://github.com/pywire/pywire/commit/ccd18c14ea7c716586264a23185348fcf9f01e6d))
- pin pyodide-build to 0.32.x for Pyodide 0.29.3 compatibility and remove generated static files from git ([078cbda](https://github.com/pywire/pywire/commit/078cbdadca5bebc85f387c3ed4977f1ddaa1cc12))
- playwright install and fix deprecation in tsconfig ([5e7c094](https://github.com/pywire/pywire/commit/5e7c0947a19ffa085295dea695dcb4531b52794c))
- **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
- **pywire-docs:** bump astro, starlight, and starlight-llms-txt ([56ad193](https://github.com/pywire/pywire/commit/56ad19321ecffd90ee64dc59e8e38c9c397f5a54))
- **pywire-docs:** sync package.json specifiers with lockfile ([5c9b6d5](https://github.com/pywire/pywire/commit/5c9b6d5388dfd2d77af676b1ac3ae521bbef2d92))
- **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))
- **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
- **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
- remove tree-sitter submodule and fix tsconfig relative path issues ([931d387](https://github.com/pywire/pywire/commit/931d3870e47a6d19d057d6c561ea4ee6b00265a4))
- resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
- **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
- use stable Rust instead of nightly for docs wasm build ([517796f](https://github.com/pywire/pywire/commit/517796f4922b8aeb7065d4bdb0b45779661702e7))
- **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))
