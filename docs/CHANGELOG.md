# Changelog

## [0.5.16](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.15...pywire-docs-v0.5.16) (2026-05-03)


### Bug Fixes

* **pywire-docs:** own iframe history + sync files without restart ([#208](https://github.com/pywire/pywire/issues/208)) ([7066383](https://github.com/pywire/pywire/commit/7066383a0997bb62a166989e84b707e2d5dba550))

## [0.5.15](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.14...pywire-docs-v0.5.15) (2026-05-03)


### Bug Fixes

* **pywire-docs:** tutorial sweep — validator, monaco, content fixes ([#205](https://github.com/pywire/pywire/issues/205)) ([c56ea4a](https://github.com/pywire/pywire/commit/c56ea4a14e19809df9b669f021e25724395510b5))

## [0.5.14](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.13...pywire-docs-v0.5.14) (2026-05-03)


### Bug Fixes

* **pywire-docs:** defer adapter creation until all step files written ([adf8ede](https://github.com/pywire/pywire/commit/adf8ede79b5261db8d9aa8ca0e86800a36113a82))

## [0.5.13](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.12...pywire-docs-v0.5.13) (2026-05-03)


### Bug Fixes

* **pywire-docs:** make WS cleanup synchronous and avoid ws_connect race ([59911d7](https://github.com/pywire/pywire/commit/59911d792a3a929c425533f96964803c0097704b))

## [0.5.12](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.11...pywire-docs-v0.5.12) (2026-05-03)


### Bug Fixes

* **pywire-docs:** add project root to sys.path in shim ([2c85ddf](https://github.com/pywire/pywire/commit/2c85ddf43cd3603795d29551b6b8b37b6bc711d9))

## [0.5.10](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.9...pywire-docs-v0.5.10) (2026-05-03)


### Bug Fixes

* **pywire-docs:** disconnect old WS on restart to silence ping timeout ([4e92cbf](https://github.com/pywire/pywire/commit/4e92cbfd012a10d15d5fcebb6537aeff0bd6050e))

## [0.5.9](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.8...pywire-docs-v0.5.9) (2026-05-03)


### Bug Fixes

* **pywire-docs:** revert pong-drop; add PyPI version-check cache ([#193](https://github.com/pywire/pywire/issues/193)) ([6bce104](https://github.com/pywire/pywire/commit/6bce104e72903ebc4fa6a280744bbab660114ccb))

## [0.5.8](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.7...pywire-docs-v0.5.8) (2026-05-02)


### Bug Fixes

* **pywire-docs:** keepalive pings prevent WS heartbeat disconnect ([#190](https://github.com/pywire/pywire/issues/190)) ([602527d](https://github.com/pywire/pywire/commit/602527d22d7217efb7245008a0cbd4801ca5ad16))

## [0.5.1](https://github.com/pywire/pywire/compare/pywire-docs-v0.5.0...pywire-docs-v0.5.1) (2026-04-13)


### Bug Fixes

* **pywire-docs:** convert index_urls to Python list; fix nightly vs production deploy routing ([66eefe4](https://github.com/pywire/pywire/commit/66eefe45a54ff4eed6935a01ff5ff5ec93bcce55))
* **pywire-docs:** set CDN+PyPI index once before all installs ([25eac33](https://github.com/pywire/pywire/commit/25eac33cb7f91553feb061933b97ccecb9923fea))
* **pywire-docs:** use set_index_urls for CDN; fix PyPI WASM filter for pyodide tag ([67d10cf](https://github.com/pywire/pywire/commit/67d10cfe330fe3e231376db7e63739153cee5ee7))
* **pywire-docs:** use set_index_urls with CDN+PyPI for micropip ([062f5a4](https://github.com/pywire/pywire/commit/062f5a4b6f4e0243b5098c9544e433709455aacf))
* **tree-sitter-pywire:** allow pre-release deps for pyodide-build==0.29.3 ([585cb90](https://github.com/pywire/pywire/commit/585cb902727e6df6acd67d5c29bc80a4054b6fff))
* **tree-sitter-pywire:** pin pyodide-build==0.29.3 for correct platform tags; fix micropip install ([d32c7f9](https://github.com/pywire/pywire/commit/d32c7f90e8e7d9761a9dafe4eb672fda72087473))
* **tree-sitter-pywire:** pin wheel&lt;0.44 for auditwheel_emscripten compat ([5d5de0f](https://github.com/pywire/pywire/commit/5d5de0ff12cf1a2469570d7234a562d3c15d11c7))

## [0.5.0](https://github.com/pywire/pywire/compare/pywire-docs-v0.4.1...pywire-docs-v0.5.0) (2026-04-13)


### Features

* **tree-sitter-pywire:** upload WASM wheel to pywire.dev/cdn/ on release ([d84188a](https://github.com/pywire/pywire/commit/d84188ae58ae5e512b1a85c8d76e7d306fc3755c))


### Bug Fixes

* **tree-sitter-pywire:** pin emsdk via pyodide config get emscripten_version ([21dac35](https://github.com/pywire/pywire/commit/21dac3594cc1967340bb5f88a969ca99a00a5742))

## [0.4.1](https://github.com/pywire/pywire/compare/pywire-docs-v0.4.0...pywire-docs-v0.4.1) (2026-04-13)


### Bug Fixes

* **pywire-docs:** fix esbuild --define quoting for execFileSync ([fcbb846](https://github.com/pywire/pywire/commit/fcbb846831b1e0a5dfe69f56ce615c0abb2a88fe))

## [0.4.0](https://github.com/pywire/pywire/compare/pywire-docs-v0.3.0...pywire-docs-v0.4.0) (2026-04-13)


### Features

* pure Python build — pywire-parser, Pyodide adapter, Cloudflare Workers deploy ([#87](https://github.com/pywire/pywire/issues/87)) ([3c713d2](https://github.com/pywire/pywire/commit/3c713d2c68b6098c51780f3a9820e8bd7536f898))

## [0.3.0](https://github.com/pywire/pywire/compare/pywire-docs-v0.2.0...pywire-docs-v0.3.0) (2026-04-13)


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
