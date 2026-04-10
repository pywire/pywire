# Changelog

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
