# Changelog

## [0.14.3](https://github.com/pywire/pywire/compare/pywire-v0.14.2...pywire-v0.14.3) (2026-05-04)


### Bug Fixes

* auth-demo SPA cookie + codegen scope + -in-for regressions ([#191](https://github.com/pywire/pywire/issues/191)) ([3527ac3](https://github.com/pywire/pywire/commit/3527ac34abb1e57b88fe7dfdbc917ed17b22e256))
* error-system overhaul (line numbers, design system, SPA leak) ([#241](https://github.com/pywire/pywire/issues/241)) ([911d5b1](https://github.com/pywire/pywire/commit/911d5b1cae6ae895b5bf59fb09a15ba44a710cd8))
* re-record breaking change for release-please after squash-merge ([#247](https://github.com/pywire/pywire/issues/247)) ([f5b5aee](https://github.com/pywire/pywire/commit/f5b5aee9605f227e16a6ee3ecbf6f0790d5fd41c))

## [0.14.2](https://github.com/pywire/pywire/compare/pywire-v0.14.1...pywire-v0.14.2) (2026-05-03)


### Bug Fixes

* **pywire:** bind props namespace + seat snippet kwargs on first paint ([#204](https://github.com/pywire/pywire/issues/204)) ([e7f6e8b](https://github.com/pywire/pywire/commit/e7f6e8b3b1d522da4c8f840da14d02c32408b437))

## [0.14.1](https://github.com/pywire/pywire/compare/pywire-v0.14.0...pywire-v0.14.1) (2026-05-03)


### Bug Fixes

* **pywire:** add jinja2 to [cli] extra for dev-mode error pages ([c704c5a](https://github.com/pywire/pywire/commit/c704c5a919aa91d63bba8be2c77cc54e50380fff))

## [0.14.0](https://github.com/pywire/pywire/compare/pywire-v0.13.0...pywire-v0.14.0) (2026-05-02)


### Features

* cross-package version floors with runtime checks ([#181](https://github.com/pywire/pywire/issues/181)) ([9ec02a3](https://github.com/pywire/pywire/commit/9ec02a330d500ceb83a24547e6012acd1d828137))

## [0.13.0](https://github.com/pywire/pywire/compare/pywire-v0.12.1...pywire-v0.13.0) (2026-05-01)


### Features

* $dynamic memo escape, !no_interactive, component memo, class/style bind, oneliner blocks ([#175](https://github.com/pywire/pywire/issues/175)) ([8723f51](https://github.com/pywire/pywire/commit/8723f51a1414ad46421047c583ee49f7a4229138))

## [0.12.1](https://github.com/pywire/pywire/compare/pywire-v0.12.0...pywire-v0.12.1) (2026-04-22)


### Bug Fixes

* promote pywire-parser to base dep; refresh LS install; 5min update poll ([9823396](https://github.com/pywire/pywire/commit/9823396f1b8e57ae40331cc685af79285032d78f))

## [0.12.0](https://github.com/pywire/pywire/compare/pywire-v0.11.4...pywire-v0.12.0) (2026-04-22)


### Features

* split pywire CLI, add pywire check static analysis, oneliner scaffolder ([#156](https://github.com/pywire/pywire/issues/156)) ([d2b8a9d](https://github.com/pywire/pywire/commit/d2b8a9dff0871ff1d9b4cabc64a855842c48fbb6))


### Bug Fixes

* **pywire:** lazy-import rich in runtime logging ([#166](https://github.com/pywire/pywire/issues/166)) ([11f82eb](https://github.com/pywire/pywire/commit/11f82ebd932f7ca963f3e9f4442d9ebdf99f72c1))
* **pywire:** strip ANSI + Rich markup from browser-forwarded logs ([#157](https://github.com/pywire/pywire/issues/157)) ([1e228b0](https://github.com/pywire/pywire/commit/1e228b0da9d7cf74847ce5547b1271bfed6facf5))

## [0.11.4](https://github.com/pywire/pywire/compare/pywire-v0.11.3...pywire-v0.11.4) (2026-04-20)


### Bug Fixes

* **pywire:** skip &lt;script&gt;/&lt;style&gt; bodies when searching HTML for structural tags ([a5515da](https://github.com/pywire/pywire/commit/a5515daf7328587ed92715e356c559e2eaed5da3))

## [0.11.3](https://github.com/pywire/pywire/compare/pywire-v0.11.2...pywire-v0.11.3) (2026-04-20)


### Bug Fixes

* **pywire:** sequence non-async &lt;script src&gt; before later scripts on SPA nav ([e18f964](https://github.com/pywire/pywire/commit/e18f9649abeb2183a5969e644fe189b3ff587db0))

## [0.11.2](https://github.com/pywire/pywire/compare/pywire-v0.11.1...pywire-v0.11.2) (2026-04-20)


### Bug Fixes

* **pywire:** handle @keyframes/[@media](https://github.com/media) correctly in scoped CSS ([a35d2c2](https://github.com/pywire/pywire/commit/a35d2c2813da0b7f5d0cba77c1cc339d341ae3ba))
* **pywire:** inject collected styles into the first &lt;/head&gt; ([1b6a839](https://github.com/pywire/pywire/commit/1b6a8392c911ae002fc4a2f709dbd8a7d2a628d3))
* **pywire:** namespace region IDs per compilation unit ([ffeb3cc](https://github.com/pywire/pywire/commit/ffeb3cc169e771ee2dccbbdb99476f515266e0f3))
* **pywire:** skip framework artifacts in session snapshot ([8ef823f](https://github.com/pywire/pywire/commit/8ef823f809daf0f327c3e9330edf72325db0386d))

## [0.11.1](https://github.com/pywire/pywire/compare/pywire-v0.11.0...pywire-v0.11.1) (2026-04-20)


### Bug Fixes

* **pywire:** enable &lt;style scoped&gt; on layout-based pages ([07af048](https://github.com/pywire/pywire/commit/07af048f7b96749ecd08ec4b0b411df437686241))

## [0.11.0](https://github.com/pywire/pywire/compare/pywire-v0.10.0...pywire-v0.11.0) (2026-04-20)


### Features

* **pywire:** {\$auth} template directive + auth runtime integration ([5717f4d](https://github.com/pywire/pywire/commit/5717f4d0cee8b03949de86ec9d8b95e396f16ff5))

## [0.10.0](https://github.com/pywire/pywire/compare/pywire-v0.9.0...pywire-v0.10.0) (2026-04-20)


### Features

* render regions (snippets, $render, $head) — retire slots ([#127](https://github.com/pywire/pywire/issues/127)) ([d2b48b6](https://github.com/pywire/pywire/commit/d2b48b635a4263b1568b0302e09875a5557c8004))

## [0.9.0](https://github.com/pywire/pywire/compare/pywire-v0.8.0...pywire-v0.9.0) (2026-04-18)


### Features

* **pywire:** add configurable dev server port ([82b11f4](https://github.com/pywire/pywire/commit/82b11f4cbc19fe5e354858ef0daf1b41dd4f4191))
* **pywire:** pre-warm CF Durable Object during HTTP request ([72673a2](https://github.com/pywire/pywire/commit/72673a26ac1fb3a8874aa9439feb7ea5537ff08a))


### Bug Fixes

* **pywire:** align dev server logs with uvicorn format via Rich handler ([f1684c6](https://github.com/pywire/pywire/commit/f1684c6bdf1d68432e9901004a916dcf7f5029f6))
* **pywire:** clean dev server shutdown via client broadcast ([06f4e98](https://github.com/pywire/pywire/commit/06f4e98b5ea3e56902b35358975eb5e367bbf3e0))
* **pywire:** decouple internal framework logging from debug flag ([e2998fc](https://github.com/pywire/pywire/commit/e2998fc3be4f2b2ff9065b7c8f3f7c04e0c11e66))
* **pywire:** fix hot reload breaking interactivity on pages with layouts ([e83d6f0](https://github.com/pywire/pywire/commit/e83d6f0e7b470de75629758277d119ab0e83a557))
* **pywire:** fix WireList equality recursion, ImportError surfacing, and $for component cleanup ([c7afde4](https://github.com/pywire/pywire/commit/c7afde4d8ec094bf24beabb9afec66b6cbe8031a))
* **pywire:** force uvicorn exit and show correct startup URL ([6498047](https://github.com/pywire/pywire/commit/649804771fc8adc7b93452c932ddbef324752137))
* **pywire:** implement [@click](https://github.com/click).once modifier in event handler ([ccfdc0f](https://github.com/pywire/pywire/commit/ccfdc0f31ff7720e8d4ff0db38354c3a0d2cf1da)), closes [#86](https://github.com/pywire/pywire/issues/86)
* **pywire:** remove duplicate reconnect toast in dev mode ([1b33a93](https://github.com/pywire/pywire/commit/1b33a933c0fbfd616e9e78431d8a01de1517658f))

## [0.8.0](https://github.com/pywire/pywire/compare/pywire-v0.7.0...pywire-v0.8.0) (2026-04-15)


### Features

* **pywire:** make pydantic optional, fix CF Workers cold start and deployment ([b891602](https://github.com/pywire/pywire/commit/b891602f92fd7bedee721884e5eaf8cd14dd81c2))

## [0.7.0](https://github.com/pywire/pywire/compare/pywire-v0.6.0...pywire-v0.7.0) (2026-04-15)


### Features

* **pywire:** improve deploy CLI platform UX ([2aa64ec](https://github.com/pywire/pywire/commit/2aa64ec9b33260495fd073d709ad6ba70b01a399))


### Bug Fixes

* **pywire:** defer heavy imports in CF Workers templates to avoid startup CPU limit ([2dd41df](https://github.com/pywire/pywire/commit/2dd41df0331e2c368ece41dd174bbcfb49972944))
* **pywire:** suppress debug logs by default ([4aeffed](https://github.com/pywire/pywire/commit/4aeffed55fa7e2b2c81911a0b8010534276d74fa))

## [0.6.0](https://github.com/pywire/pywire/compare/pywire-v0.5.0...pywire-v0.6.0) (2026-04-15)


### Features

* Cloudflare Python Workers support ([#110](https://github.com/pywire/pywire/issues/110)) ([9866d10](https://github.com/pywire/pywire/commit/9866d1096b31cf34758d33b8728ae318b0bc1566))
* **tree-sitter-pywire:** upload WASM wheel to pywire.dev/cdn/ on release ([d84188a](https://github.com/pywire/pywire/commit/d84188ae58ae5e512b1a85c8d76e7d306fc3755c))

## [0.5.0](https://github.com/pywire/pywire/compare/pywire-v0.4.0...pywire-v0.5.0) (2026-04-13)


### Features

* pure Python build — pywire-parser, Pyodide adapter, Cloudflare Workers deploy ([#87](https://github.com/pywire/pywire/issues/87)) ([3c713d2](https://github.com/pywire/pywire/commit/3c713d2c68b6098c51780f3a9820e8bd7536f898))

## [0.4.0](https://github.com/pywire/pywire/compare/pywire-v0.3.0...pywire-v0.4.0) (2026-04-13)


### Features

* **pywire:** reconnect overlay, lifecycle hooks, typed refs, dispatch, media refs ([#85](https://github.com/pywire/pywire/issues/85)) ([9a8b43d](https://github.com/pywire/pywire/commit/9a8b43d4868e9a2149f85f597112275ea5425c7b))

## [0.3.0](https://github.com/pywire/pywire/compare/pywire-v0.2.7...pywire-v0.3.0) (2026-04-10)


### Features

* stores, middleware, context API, deploy CLI, event optimization, and cache busting ([#43](https://github.com/pywire/pywire/issues/43)) ([00e55d1](https://github.com/pywire/pywire/commit/00e55d18a177a9cdb1378eaede2969f30b91f9ff))


### Bug Fixes

* **pywire:** gate debug logs behind logger.debug and fix hot reload lifecycle ([f0de813](https://github.com/pywire/pywire/commit/f0de813868771fb2d628b44717ba48fb75d38127))

## [0.2.7](https://github.com/pywire/pywire/compare/pywire-v0.2.6...pywire-v0.2.7) (2026-04-08)


### Bug Fixes

* **pywire:** resolve explicit static_dir relative to project root ([c95f252](https://github.com/pywire/pywire/commit/c95f252c05743ca3f4570270adadb99ae90b657d))

## [0.2.6](https://github.com/pywire/pywire/compare/pywire-v0.2.5...pywire-v0.2.6) (2026-04-08)


### Bug Fixes

* **pywire:** resolve explicit pages_dir relative to project root ([ae753f1](https://github.com/pywire/pywire/commit/ae753f1a7605a4e1bea521738e18bd87c24ac2cb))

## [0.2.5](https://github.com/pywire/pywire/compare/pywire-v0.2.4...pywire-v0.2.5) (2026-04-07)


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **pywire-language-server:** bump for release ([88aa449](https://github.com/pywire/pywire/commit/88aa449a1a55ece6145f1f21bc7b1ca807e394ca))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* **tree-sitter-pywire:** bump for consistency ([42b40bd](https://github.com/pywire/pywire/commit/42b40bd3ec2711445865c772573b52774857bbc0))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## [0.2.4](https://github.com/pywire/pywire/compare/pywire-v0.2.3...pywire-v0.2.4) (2026-04-07)


### Bug Fixes

* add intermediate directories to sys.path for dotted module imports ([3bed80f](https://github.com/pywire/pywire/commit/3bed80fd21d867e3fa67172a22bc9f19bf130c99))

## [0.2.3](https://github.com/pywire/pywire/compare/pywire-v0.2.2...pywire-v0.2.3) (2026-04-07)


### Bug Fixes

* use license file reference and skip CI for release-please commits ([5816944](https://github.com/pywire/pywire/commit/5816944a2bd012001c8b0bf3e17e1ff78746da36))

## [0.2.2](https://github.com/pywire/pywire/compare/pywire-v0.2.1...pywire-v0.2.2) (2026-04-07)


### Bug Fixes

* commit Cargo.lock for reproducible wheel builds, add project URLs ([f8d6864](https://github.com/pywire/pywire/commit/f8d68640c1812fb41db21da97ea23199fe78f69b))
* move project.urls after all project keys to fix TOML parsing ([e602fce](https://github.com/pywire/pywire/commit/e602fce507a1dd99f95586788d25829d71e6ccda))

## [0.2.1](https://github.com/pywire/pywire/compare/pywire-v0.2.0...pywire-v0.2.1) (2026-04-07)


### Bug Fixes

* add PyPI classifiers to pywire package metadata ([2b4eff7](https://github.com/pywire/pywire/commit/2b4eff719755f3ae75195727f333712e8b802755))

## [0.2.0](https://github.com/pywire/pywire/compare/pywire-v0.1.10...pywire-v0.2.0) (2026-04-07)


### Features

* `pywire dev` TUI ([6df3d5a](https://github.com/pywire/pywire/commit/6df3d5a09eb741acaa912c5cd2bb4b40490d6fad))
* $permanent (for preserving elements) and $reload (for bypassing SPA) ([37034b4](https://github.com/pywire/pywire/commit/37034b4690f97a7033e49d121fcfba65051b10bc))
* add `wire` primitive to be explicitly reactive and properly handle state and scoping issues ([64f7adc](https://github.com/pywire/pywire/commit/64f7adc52f904a924b53c17d7781a8e838df4058))
* apply working changes from polyrepo ([9377037](https://github.com/pywire/pywire/commit/937703754404ee07308a75e75bad22a4fd03e5cc))
* CI, docs & publish on v* tag ([ee12524](https://github.com/pywire/pywire/commit/ee125244f31bccd90fe4b6bcca9152d508edcd21))
* Consolidate style and structure for framework built-in pages like compile error and 404 error, 500 error, etc. ([b1adfb4](https://github.com/pywire/pywire/commit/b1adfb4d2df7db95348dd650253d62f81943305f))
* control flow blocks docs ([1f28476](https://github.com/pywire/pywire/commit/1f284760e25c888e8ea23d67249bc7128511fc5e))
* docs build step to CI ([4c1bcfe](https://github.com/pywire/pywire/commit/4c1bcfe72a02a1894ab524badd0c7b6982149a57))
* docs publish trigger separate from v* ([c54c339](https://github.com/pywire/pywire/commit/c54c3393c9be1340defc45460da742e82844be1f))
* docs tutorial ux improvements, success, multiple files, stability improvements ([9ba629c](https://github.com/pywire/pywire/commit/9ba629c75cc0d794f7b91c947add8aea8f5548c5))
* flipped pywire grammar; directives (optional), python (optional), then html. ([3fd4c44](https://github.com/pywire/pywire/commit/3fd4c4492e541ec58f309e997188c5cf50fa6315))
* hide verbose debug logs for deployments, fix test scripts ([3a7c65c](https://github.com/pywire/pywire/commit/3a7c65cf8a6d78107d1d0d1da38cfe6b042a0117))
* improving docs, added llms-txt ([a4767cf](https://github.com/pywire/pywire/commit/a4767cf9e68d9efd0a960dfddccc767f9baa2265))
* inline html blocks for `if`, `for`, `try`, and `await` expressions ([5042e6c](https://github.com/pywire/pywire/commit/5042e6c2a1c67234dfc37ac4f6930efdc41269cf))
* introduce dynamic versioning via git tags with hatch-vcs ([65f791d](https://github.com/pywire/pywire/commit/65f791d9f53bd4682c8ea50d9502c4f47539859c))
* readme with install scripts ([f111083](https://github.com/pywire/pywire/commit/f111083dd871bc43ca6166e9f5dbb7fdda4f2066))
* redirect page with step memory ([89c938b](https://github.com/pywire/pywire/commit/89c938b9e0aff86fbfb928efe5b4562b060e205f))
* remember tutorial step ([8e17c0b](https://github.com/pywire/pywire/commit/8e17c0b0cd52ee503d45ae3a7f5dc7d26eca7898))
* restructure monorepo, add CI/deploy workflows ([5127c56](https://github.com/pywire/pywire/commit/5127c56dd38542eda545b27693ec4b2e4b9e6152))
* TUI and cli improvements in good state but work in progress ([6f1296f](https://github.com/pywire/pywire/commit/6f1296f8fc5f58d0f1d147aa5c3173da7f325dc9))
* tutorial workspace is in a very good place now, going to start building out tutorials ([2b8df90](https://github.com/pywire/pywire/commit/2b8df90a4dffe8eb3ce36bc1a4273c3bad0bab1b))
* ty and nox for type checking and multi-version testing. performed lint and fixed lint script on docs ([2a6a2e8](https://github.com/pywire/pywire/commit/2a6a2e8c162e0b48db02fff47dba2972f8691b01))
* v0.1.9 mostly feature ready. need to do final validation and CI testing. ([4746577](https://github.com/pywire/pywire/commit/474657701acc6b842763a90924c0abb635cba9e8))
* wire comparisons, client script not injected without spa mode on, using maturin for builds ([422eed2](https://github.com/pywire/pywire/commit/422eed23b5b0e2ba12c9286c1132fa47b61bd361))
* working on docs & interactive tutorial. in a good place to commit but still very much WIP ([14b891b](https://github.com/pywire/pywire/commit/14b891baa48edaa5b9d633ee4c94bd57ce4959ac))


### Bug Fixes

* adapt internal references for monorepo layout ([a260035](https://github.com/pywire/pywire/commit/a26003572b9ae460ce36f3e4a5e41881ad7115a4))
* all tests passign and lint ([85ff025](https://github.com/pywire/pywire/commit/85ff025dde4d1c645601da53614c72b5b7a13cc0))
* all top-level statements in the page instance scope to resolve variable scoping issues ([0166238](https://github.com/pywire/pywire/commit/01662383ec8b6e062eb53e5789ed31981854665f))
* assets build issue, shiki config issue in production ([323f0a3](https://github.com/pywire/pywire/commit/323f0a3913e49863aff5c33de4632faf52d6cf10))
* build for WASM pyodide ([8bdd755](https://github.com/pywire/pywire/commit/8bdd7551006574cfc1ff7c948d1c93c5543cae07))
* bump ([563f966](https://github.com/pywire/pywire/commit/563f96656f246bdf1a33e73d354f77d5d48ce4bb))
* bundle static assets into bundle ([66e63e1](https://github.com/pywire/pywire/commit/66e63e129c236d27e827dd2487beb695f35ab6d8))
* check, lint, and fix CI & hatch build error ([097cc61](https://github.com/pywire/pywire/commit/097cc61ec215357759721d0c7476c1d06b6cccb4))
* CI ([2955c52](https://github.com/pywire/pywire/commit/2955c52edfcb949c30dc03e6d3c94818db1ce369))
* CI ([ca2e528](https://github.com/pywire/pywire/commit/ca2e528c05f50b2e60fed76316ded6b552f81181))
* CI workflow installs only what each job needs ([e98d2cc](https://github.com/pywire/pywire/commit/e98d2cca2a27ba8d1f138031124345dabdcca247))
* CI, linting, tests. Also fix base URL for tutorial when routing ([f1f7fb7](https://github.com/pywire/pywire/commit/f1f7fb775e52adc745407975405a618b9d5d6707))
* **CI:** build client before tests ([28f5640](https://github.com/pywire/pywire/commit/28f5640b4cd9166aca75c1962734d576c53f027c))
* **CI:** build client in publish ([cdeefb8](https://github.com/pywire/pywire/commit/cdeefb8b74e71bb06ef1bf289c43016169129988))
* **ci:** build manylinux for publish ([e49bef0](https://github.com/pywire/pywire/commit/e49bef028e34abc6e15a3f2915958f9797b4d550))
* **ci:** bumping pyodide and emscripten? restore the publish job ([1006691](https://github.com/pywire/pywire/commit/10066918b2f3614519f206affd87c872ea909a99))
* **ci:** checkout tree-sitter dependency ([d677b67](https://github.com/pywire/pywire/commit/d677b67136dd846f1c461df4dbafa3d53c0befee))
* **ci:** correct emscriptem version, docs-wasm-build was in the wrong location ([93e76e5](https://github.com/pywire/pywire/commit/93e76e533b4771cd7e0eb6d904009fc612452c5d))
* **ci:** deploy docs includes tree-sitter since it builds pywire too ([a736e7f](https://github.com/pywire/pywire/commit/a736e7fc875992ee41b26e49a67c77934ef86fa2))
* **ci:** deploy docs wasm build should work now ([f25b000](https://github.com/pywire/pywire/commit/f25b000fba89e3bb8dee4ac4fcdcc83a21cc806c))
* **ci:** don't build wasm lib for publish, still trying to fix docs wasm build ([994a048](https://github.com/pywire/pywire/commit/994a048355bc178458313182085c01c89d348f83))
* **ci:** extract version from tag manually since build process modifies package.json causing subsequent builds to be in a dirty state ([9a8785e](https://github.com/pywire/pywire/commit/9a8785e3fe866f49649e64ebe67f4c6ec4001f58))
* **ci:** got pywire to build for pyodide locally, working on making it work for CI via act ([811be28](https://github.com/pywire/pywire/commit/811be28b313fb8c6604f0b90f6d2edf2145d57ba))
* **ci:** had regression with pyodide version, ([bbc4df4](https://github.com/pywire/pywire/commit/bbc4df41ad29c5d69c473082d7526163440fa70f))
* **ci:** install rust for linux container? ([55dea2c](https://github.com/pywire/pywire/commit/55dea2cccba7e6d048793770dd643455a30ad150))
* **ci:** issue with client build, bump client version ([37eb324](https://github.com/pywire/pywire/commit/37eb32491515f497b3ad9ee813f219c443c2282f))
* **ci:** just manually pin vendored tree-sitter-pywire dep with git to uncomplicate CI ([d8eb899](https://github.com/pywire/pywire/commit/d8eb899d852e7c2e22522586372b03f84c84d0e1))
* **ci:** lockfile ([9a049e6](https://github.com/pywire/pywire/commit/9a049e6d9e1ca35d3bc520049c44077c4ddbcf16))
* **ci:** needs rust ([719544a](https://github.com/pywire/pywire/commit/719544a5efb2dad0494f9ebdb8cea5a95d7e0d55))
* **ci:** publish needs tree-sitter, still trying to fix WASM build for docs ([37f89e8](https://github.com/pywire/pywire/commit/37f89e890285223d738b4eb8f63e2a2ea3ab8f53))
* **ci:** publish use shell bash for windows for consistency of git tag selection ([45ca4d6](https://github.com/pywire/pywire/commit/45ca4d6ba2773f6672e280a190f250ff53a5559c))
* **ci:** setup rust flags to fix linker issue, remove separate docs wasm build. ([1539433](https://github.com/pywire/pywire/commit/1539433e44a5459fede82a27dc15548d9606a3fe))
* **ci:** should be final fix for publish, SETUPTOOLS_SCM_PRETEND_VERSION was overriden by linux specific env vars ([54729c6](https://github.com/pywire/pywire/commit/54729c6e793c482052c91f12876000e037e1de70))
* **ci:** still trying to disable a memory flag to satisfy emcc ([a040089](https://github.com/pywire/pywire/commit/a040089d2c6146be31480a4cb2a25c3b76ad780e))
* **ci:** still trying to disable memory flag ([84e2771](https://github.com/pywire/pywire/commit/84e2771ac19f968756fc33c7d925ab10b799343c))
* **ci:** still trying to pass CI for main build and wasm ([e04f1e2](https://github.com/pywire/pywire/commit/e04f1e21adecab43f4096b3f7d35dc13e4196151))
* **ci:** still working on resolving main CI & wasm builds ([fa9d491](https://github.com/pywire/pywire/commit/fa9d491368a3793f2d85ed7811f7d9b1d0fcbd99))
* **ci:** trying adding tree-sitter-pywire as a sumbodule else to get it as dependency working for publish ([6843b3b](https://github.com/pywire/pywire/commit/6843b3babd2ecbfd2fd74c44e3fc08951e527b5d))
* **ci:** was only building emscripten in build-assets. docs wasm needs tree-sitter checked out ([69deb99](https://github.com/pywire/pywire/commit/69deb99a241fba18c89779914147b2ff8c3453d1))
* exclude node_modules from sdist, improve bundling assets process for CI, working on tutorial workspace bugs still ([cc4b019](https://github.com/pywire/pywire/commit/cc4b019284664032a0d2e50b2d94db0d1a46be1d))
* fixed a major issue with the browser preview and serving where interactivity caused iframe dom bugs. built out some more tutorials (wip) and an outline of the tutorials ([35d9405](https://github.com/pywire/pywire/commit/35d94053b328c1eb47dfdf9edcae0e991e5d2b89))
* for base url issue nuclear option ([fb7cdbf](https://github.com/pywire/pywire/commit/fb7cdbfb4c6c14fb327060b8e208d1b173e57008))
* force include static assets, dev server loads dev certs correctly (bug) ([3e5612c](https://github.com/pywire/pywire/commit/3e5612c0031beefe6503392155b4228e53b6a0be))
* forgot to bump ([795bfd4](https://github.com/pywire/pywire/commit/795bfd478e31ac3d24cc37b2ecc4b57fbb1432a8))
* got llms-txt properly working ([467fa3d](https://github.com/pywire/pywire/commit/467fa3d1d1f37e131e6642311266f68c36714284))
* lint ([9e3413b](https://github.com/pywire/pywire/commit/9e3413be9f829b5b7262baffab009e525d1493c9))
* lint ([c3f08aa](https://github.com/pywire/pywire/commit/c3f08aa8277470a9b2a82e53c6362795b350c08a))
* lint ([4226eb5](https://github.com/pywire/pywire/commit/4226eb55afe13d9f1a3d05eeed4d0025c6974a0a))
* lxml temp fix for windows ([d3291cc](https://github.com/pywire/pywire/commit/d3291cc28b28c3b5467a6a5da490f0a283737587))
* maybe trailing slashes ([7855453](https://github.com/pywire/pywire/commit/78554539b7865a22a3ad1310e1d8fc68d461e1ea))
* missed data-astro-reload in the hierarchy ([d734a35](https://github.com/pywire/pywire/commit/d734a35b676bce9c21954e95d4aba3a43cdaf1be))
* missing UV in CI ([04a676e](https://github.com/pywire/pywire/commit/04a676ecd64bf71e7a6e62918f224cd2f223f884))
* more robust error handling when pulling in pywire from sdist and no pnpm ([bc6de36](https://github.com/pywire/pywire/commit/bc6de36eb26cf8ab836ea6c864a3beef718d4837))
* moving subdir scripts to top-level to comply with pattern. trying to fix hatch_build to properly build sdist on windows ([a89cf8d](https://github.com/pywire/pywire/commit/a89cf8dbdb380606d6426265324c975b129d98df))
* needed to run check ([f9d356f](https://github.com/pywire/pywire/commit/f9d356f79efa15adb73e5a338e512ae5358147e8))
* only built deps required for pnpm 10 ([5881133](https://github.com/pywire/pywire/commit/5881133105e2d02428686e8de51c9ce8632df370))
* oops lint ([c6c4e0a](https://github.com/pywire/pywire/commit/c6c4e0a900f6e21ba2f5c636b761402248596bd6))
* potential security flaws in XSS, pywire handler abuse potential (RCE) ([7e62cb3](https://github.com/pywire/pywire/commit/7e62cb3f7bfd77371aed9b03a9a522a2408bbb09))
* refactor to anchor tags for more explicit control, view transitions should still intercept ([8fdd8c7](https://github.com/pywire/pywire/commit/8fdd8c74ba6b004a340b562f35aeaff08460892f))
* **release:** build client before publish ([3789887](https://github.com/pywire/pywire/commit/378988794c64f9ab981c899cea113be39e7e33bc))
* **release:** include all of pywire in wheell ([c17374d](https://github.com/pywire/pywire/commit/c17374dd60981c336ad34cbdc2a4021f1dc93103))
* remove built JS from index, bump all version refs to 0.1.0 ([966db13](https://github.com/pywire/pywire/commit/966db1366bb6076d6d3bc3301a7a7f605ea87557))
* remove data-astro-reload on links to prevent hard loads ([de23800](https://github.com/pywire/pywire/commit/de23800d003f86ca90ed080a84f519eb58baf117))
* remove deprecated WIP tags, update docs grammar ([12c7fdc](https://github.com/pywire/pywire/commit/12c7fdca88ce328611f427f8f14129bb1f3a3116))
* remove tree-sitter submodule and fix tsconfig relative path issues ([931d387](https://github.com/pywire/pywire/commit/931d3870e47a6d19d057d6c561ea4ee6b00265a4))
* remove version, make sure docs* tags don't pollute releases ([7019740](https://github.com/pywire/pywire/commit/7019740ca1f0f1ff4ca24e1147f1d1205dd23630))
* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
* ruff cleared some imports ([1e740a7](https://github.com/pywire/pywire/commit/1e740a76c0065b5148f64f8295c5501490946af4))
* some docs & reset all tutorials with cmd+reset ([7fece69](https://github.com/pywire/pywire/commit/7fece69b9aa2b21f446a5ad133d5e8be0ef37447))
* still trying ([e61f3f2](https://github.com/pywire/pywire/commit/e61f3f2803a0b09a1cf12d0cb0eafbc4de2a69fa))
* still trying to fix missing base url when navving in interactive tutorial ([c780d26](https://github.com/pywire/pywire/commit/c780d26a7f86e3917446349f1ed307ee2da5de55))
* still trying to fix redirect issues ([acdb978](https://github.com/pywire/pywire/commit/acdb97891ab836ecdeec2b55b2ad6eefc5cc7e2a))
* still trying to fix the removal of /docs/ base ([843bfb4](https://github.com/pywire/pywire/commit/843bfb4ef9e5126d194f5d6679c4f253d7dccc6a))
* stop tox spinner in CI ([f874e06](https://github.com/pywire/pywire/commit/f874e065a84d97f2a114cfdc727e27d1e836cdd1))
* try again at making sdist buildable on windows ([c84578b](https://github.com/pywire/pywire/commit/c84578bbdd911fe31a24be1eb56c66a6b8f5292b))
* tutorial redirects to 404 ([218e2eb](https://github.com/pywire/pywire/commit/218e2ebc7db4057451c00106029c54085f1b4249))
* unused variable cause rust build failure ([3b37f1f](https://github.com/pywire/pywire/commit/3b37f1f9b5e272881abc19cfda9b2340cd697f02))
* use .pywire folder for all helper files/internals including build ([87df76c](https://github.com/pywire/pywire/commit/87df76cb66145c2ff5c091b15258123fc0966ed8))
* weird build error fixed CI ([bbf876c](https://github.com/pywire/pywire/commit/bbf876cfb412ee0cc461e18ee713479d5370e1fc))
