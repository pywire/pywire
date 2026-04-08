# Changelog

## [0.2.3](https://github.com/pywire/pywire/compare/tree-sitter-pywire-v0.2.2...tree-sitter-pywire-v0.2.3) (2026-04-08)


### Bug Fixes

* **tree-sitter-pywire:** fix build warning on macOS ([e3f75e7](https://github.com/pywire/pywire/commit/e3f75e7a63d738cb266d35b791aa3586d9ffb2b7))

## [0.2.2](https://github.com/pywire/pywire/compare/tree-sitter-pywire-v0.2.1...tree-sitter-pywire-v0.2.2) (2026-04-07)


### Bug Fixes

* **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))

## [0.2.1](https://github.com/pywire/pywire/compare/tree-sitter-pywire-v0.2.0...tree-sitter-pywire-v0.2.1) (2026-04-07)


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## [0.2.0](https://github.com/pywire/pywire/compare/tree-sitter-pywire-v0.1.3...tree-sitter-pywire-v0.2.0) (2026-04-07)


### Features

* CI, tests, and corpus, PNPM over NPM ([b774119](https://github.com/pywire/pywire/commit/b774119e4612990c1512ca3a8b57b6259d4cc02c))
* flipped pywire grammar; directives (optional), python (optional), then html ([d8221b2](https://github.com/pywire/pywire/commit/d8221b26a13b8b0d7a1b2ed582b5e94557028232))
* improve granularity of scopes to allow for better intellisense in LSP ([83935f8](https://github.com/pywire/pywire/commit/83935f8f0dd39399917ea7e9fe39d59c4134d1d9))
* improve tree-sitter grammar and parser to align with LSP improvements ([c64cace](https://github.com/pywire/pywire/commit/c64cace56819095e1801c45d9fefb50471e7a523))
* update grammar for pywire v0.1.8 ([49dcb8c](https://github.com/pywire/pywire/commit/49dcb8ccaaeabec0b24351010bd1586256e51726))
* update grammer for highlighting ([5a276a9](https://github.com/pywire/pywire/commit/5a276a929e9befdf3da5dbb128bd9338ffb84589))
* update tree-sitter to act as ground-truth for language; used as grammar for parser in pywrie ([073686a](https://github.com/pywire/pywire/commit/073686aacf5e7408b236e8ce17342b639803b92f))


### Bug Fixes

* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
* set C11 standard in tree-sitter-pywire build for cross-compilation ([5868dc5](https://github.com/pywire/pywire/commit/5868dc556fb3a7081a6507ba89bc2a0bc98bcb6a))
* sync tree-sitter-pywire Cargo.toml version and track it in release-please ([061e018](https://github.com/pywire/pywire/commit/061e018b1ac8a42b39e66ad9094cefc471bff180))
* sync version ([d9abc89](https://github.com/pywire/pywire/commit/d9abc89c539c2b2dce2b139e2891c175243f0f27))
* tests to align with new grammar ([a90c505](https://github.com/pywire/pywire/commit/a90c505e7b86cbb65eb8bab87b289a737c02799c))
