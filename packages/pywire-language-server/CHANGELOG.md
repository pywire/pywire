# Changelog

## [0.2.2](https://github.com/pywire/pywire/compare/pywire-language-server-v0.2.1...pywire-language-server-v0.2.2) (2026-04-07)


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))

## [0.2.1](https://github.com/pywire/pywire/compare/pywire-language-server-v0.2.0...pywire-language-server-v0.2.1) (2026-04-07)


### Bug Fixes

* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))

## [0.2.0](https://github.com/pywire/pywire/compare/pywire-language-server-v0.1.4...pywire-language-server-v0.2.0) (2026-04-07)


### Features

* apply working changes from polyrepo ([9377037](https://github.com/pywire/pywire/commit/937703754404ee07308a75e75bad22a4fd03e5cc))
* CI & publish ([f2c11a9](https://github.com/pywire/pywire/commit/f2c11a90e0a70d753ecbf83bdbf2eee60a86b659))
* completions for $var shorthand and custom attributes ([568fac5](https://github.com/pywire/pywire/commit/568fac57923f108a78c1626a0649ba5d527e3a4f))
* fix character col/line expectations in different envs ([12f738d](https://github.com/pywire/pywire/commit/12f738d40b0aa13643338b34d024fde1eacd1210))
* flipped pywire grammar; directives (optional), python (optional), then html ([0b6904e](https://github.com/pywire/pywire/commit/0b6904eb9111052bd279440619a0eefa55adada5))
* Implement LSP definition and reference fallbacks, enhance transpiler mapping with pywire parser integration, and remove old adhoc repro scripts. ([ae5f9d9](https://github.com/pywire/pywire/commit/ae5f9d931f8f70707b729efb367b1769ff1f69fd))
* improve & refactor pywire lsp to handle virtual document delegation and the new wire primitive ([cc99a2a](https://github.com/pywire/pywire/commit/cc99a2ab97decb7f50a4f9972730fc6e76f7c32a))
* improve language server shadow file generation ([e9241c1](https://github.com/pywire/pywire/commit/e9241c1a43ed0c7ec4b158f55d13dca5c8e71f02))
* introduce dynamic versioning via git tags with hatch-vcs ([787cb52](https://github.com/pywire/pywire/commit/787cb52847ba3b377fb38c0360c3cebb123ddf8b))
* language updates for v0.1.8 ([df241c4](https://github.com/pywire/pywire/commit/df241c45b522c285e6fa1c5154172d08aa5403f3))
* refactor to Ty &gt; Pylance & Pyright ([10f38a5](https://github.com/pywire/pywire/commit/10f38a5b5ccde0e197bc58ac6eea1e4f25146bf2))
* ty and nox for types and multi version testing ([23fdf54](https://github.com/pywire/pywire/commit/23fdf547d6c435d12ed0ce674a3b0421daebc609))
* update language server to support new grammar ([e1d2e2b](https://github.com/pywire/pywire/commit/e1d2e2b7035dab0f175708744f0f8b2535da5706))
* use Ty virtual document delegation instead of physical .wire.py files. ([6ae8cbe](https://github.com/pywire/pywire/commit/6ae8cbe976d935b2bd47c67fc58456e79e94a147))


### Bug Fixes

* adapt internal references for monorepo layout ([a260035](https://github.com/pywire/pywire/commit/a26003572b9ae460ce36f3e4a5e41881ad7115a4))
* add deps for CI failure ([f1d03ed](https://github.com/pywire/pywire/commit/f1d03ed9f320f82f045c157217f010aa76f685a8))
* bump to 0.1.1 since taken on pypi ([f519926](https://github.com/pywire/pywire/commit/f5199265814e0296b06baf7364bd2b60f7052083))
* correct uv syntax for adding cloned dep ([b0f76da](https://github.com/pywire/pywire/commit/b0f76da7dae60cbb06e8da27fe17fa30f2667f67))
* correctly mock stuff ([18e1fc6](https://github.com/pywire/pywire/commit/18e1fc6ff5bed63b9f13b4115caf8a4721aabe09))
* get noxfile to find pywire clone ([9222bab](https://github.com/pywire/pywire/commit/9222babdd214795b0df7187233f6bf2b0fb38dd5))
* language server works standalone ([42440aa](https://github.com/pywire/pywire/commit/42440aaa40b1523ff374da7671edbbcf7c44bf0d))
* lint ([812518a](https://github.com/pywire/pywire/commit/812518a52e1af3fc1de86c20816c5460f6634a71))
* lint script performs ty check ([72c8ca4](https://github.com/pywire/pywire/commit/72c8ca4a2eca7b34f9777ac1a34f9d08d7320c46))
* need to checkout pywire to run CI ([6fd5172](https://github.com/pywire/pywire/commit/6fd5172c6952d56e15908f210588525a381cf39c))
* pywire as dep needed for standalone LSP use ([b7e59bc](https://github.com/pywire/pywire/commit/b7e59bca28f1713813cd1ff0ded8d0281c811edf))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* remove $wire shorthand tests ([f6964bf](https://github.com/pywire/pywire/commit/f6964bfc7fb8fb0f59bbd85dce98c74a069578fd))
* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
* start bundled pyright when lsp is bundled. ([c4902d3](https://github.com/pywire/pywire/commit/c4902d346b23f88c36625f9bdee64830ec168df2))
* stop tox spinner in CI ([44758d5](https://github.com/pywire/pywire/commit/44758d523eb7bf1ce482a636426b5d7ea94cf863))
* use local pywire in CI ([750dd3a](https://github.com/pywire/pywire/commit/750dd3a75a5db4b27daa8d2de9322a54a84a69f7))
