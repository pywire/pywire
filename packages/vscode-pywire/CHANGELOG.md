# Changelog

## [0.2.1](https://github.com/pywire/pywire/compare/vscode-pywire-v0.2.0...vscode-pywire-v0.2.1) (2026-04-07)


### Bug Fixes

* **prettier-plugin-pywire:** bump for consistency ([33fc161](https://github.com/pywire/pywire/commit/33fc1613c5a70dfc4e8b00d1da3d99f2dc849925))
* **vscode-pywire:** fix CI publish with --no-dependencies flag ([1ef1d72](https://github.com/pywire/pywire/commit/1ef1d72018f4c02bf29a923dd33e4f96bdf813ac))

## [0.2.0](https://github.com/pywire/pywire/compare/vscode-pywire-v0.1.4...vscode-pywire-v0.2.0) (2026-04-07)


### Features

* apply working changes from polyrepo ([9377037](https://github.com/pywire/pywire/commit/937703754404ee07308a75e75bad22a4fd03e5cc))
* CI and publish, PNPM over NPM ([0968928](https://github.com/pywire/pywire/commit/0968928a3593ab12c85f092f9293fc99553d334d))
* **ci:** artifact vsix ([fb127df](https://github.com/pywire/pywire/commit/fb127df33e2dc8149b28d478948ccc0f3ceb12e3))
* fix warnings related to repository and number of files bundled. add update message suggesting to update pywire version in project. bundle deps improved. use latest prettierp lugin ([bb652ff](https://github.com/pywire/pywire/commit/bb652ffa6d6d9c49798b7226de61b24c80c08af5))
* flipped .wire files, goes directives (optional), python (optional), html ([e7fa319](https://github.com/pywire/pywire/commit/e7fa319f5b9d24e32150100247ad46a725e075bd))
* icon image & bump ([ddb0b52](https://github.com/pywire/pywire/commit/ddb0b52ac3ef4931f9760b11d8538c2e50e3a049))
* improve vscode language extension to leverage improved LSP and virtual document/delegation pattern ([16f3cc1](https://github.com/pywire/pywire/commit/16f3cc1218c2066bfd5d14a4a579d3273e9b6c13))
* include prettier-plugin-pywire as default formatter. ensure bundled pyright and default are seamless. works as VSIX ([dac22cf](https://github.com/pywire/pywire/commit/dac22cfd427faa22b2b6e213387aaedc9feafaa9))
* inlay hints and edge case bugs ([38e586d](https://github.com/pywire/pywire/commit/38e586d53b1e4744c81c27d98d1fbe106e89359f))
* play/stop button for .wire pages for easy start of server and open docs command ([8e6f69e](https://github.com/pywire/pywire/commit/8e6f69e2369e015470d953bae8b07672f493409a))
* remove middleware mode and pyright in favor of Ty as much faster LSP ([89c30b0](https://github.com/pywire/pywire/commit/89c30b0b8f4095e345020df0f15c6cbb6eb193cb))
* update prettier plugin and CI pulls main and release pulls latest version tag ([b337f00](https://github.com/pywire/pywire/commit/b337f00a87079f931e56afcc8be5fe9db9129a21))
* update syntax highlighting, update bundle-deps to make release jobs pull latest released version of language server, not main ([7c2619b](https://github.com/pywire/pywire/commit/7c2619bec317a43451064b1abb345c1fb11d6f41))


### Bug Fixes

* build.js =&gt; build.cjs lint ([978ce7f](https://github.com/pywire/pywire/commit/978ce7ffe7d1202049a8f4cac887f99a07342a19))
* bump ([e63671b](https://github.com/pywire/pywire/commit/e63671b79a9ebd8b8dcce7d4d07667b06561c219))
* bump ([f0ac7db](https://github.com/pywire/pywire/commit/f0ac7db5a742c1fa8e06afc24d265d5e40726829))
* bundled deps script failure in CI ([302d31d](https://github.com/pywire/pywire/commit/302d31dafce72b6e3c5f77d77ade2464dda8a684))
* CI needs pywire repo access, bundle-deps into separate script ([1d42e85](https://github.com/pywire/pywire/commit/1d42e853b6876c6d5728401200d7734020ef51b0))
* **ci:** bundle deps and script to edit tree-sitter dep path ([6679fa4](https://github.com/pywire/pywire/commit/6679fa4a6017da49001b446dfbdaa955a3cc3f51))
* **ci:** needs to include tree-sitter ([dd13881](https://github.com/pywire/pywire/commit/dd138814f509c35f56216bee365046e7c2b8a918))
* **CI:** publish failing due to missing ruff_fmt_bg.wasm, maybe not pulled in due to --no-dependencies flag missing? ([3fd1208](https://github.com/pywire/pywire/commit/3fd12083f0c82556222aecc044ff2987d549fe9b))
* **CI:** publish; add ruff fmt as a direct dependency since it might not install the transitive one ([88bb166](https://github.com/pywire/pywire/commit/88bb166ed446b4b5c73cb3470fe5dda2320af349))
* **ci:** pywire vscode ext doesn't need pywire core as a dependency ([d34d754](https://github.com/pywire/pywire/commit/d34d7540b402275b675a9cd5c4eb0222eac6ad9a))
* **CI:** still trying to find ruff_fmt_bg.wasm ([31abe38](https://github.com/pywire/pywire/commit/31abe383fd9e39b3bdace6650624fcd16978b4a2))
* **CI:** still working on getting ruff to bundle ([e4a32c4](https://github.com/pywire/pywire/commit/e4a32c421546559d49a187c5939ea4437b77069f))
* **CI:** try and reference our prettier plugin via git ([faa632a](https://github.com/pywire/pywire/commit/faa632a9775aa834ef6c83b5f0eb37cb7f3f6481))
* didn't bundle language server ([5b8de65](https://github.com/pywire/pywire/commit/5b8de65a218b8a38214ba9565924ce77ce09b4fd))
* lint ([63bbda1](https://github.com/pywire/pywire/commit/63bbda1d19ff9022bc3b1d64867a8273c53c4f50))
* lint ([cb15cd2](https://github.com/pywire/pywire/commit/cb15cd2cba919949a82797bd0e2e08b3254ebf6a))
* lint errors ([dbdeec7](https://github.com/pywire/pywire/commit/dbdeec7ed76302b07e4319ded4f91499723892fd))
* move pywire clone out of src so ts lint doesnt configure it ([6ccb5f9](https://github.com/pywire/pywire/commit/6ccb5f9d58da47fa81c2bed5b02900feff994c5b))
* pywire src dir in CI ([56c4b9a](https://github.com/pywire/pywire/commit/56c4b9a04192295dd912c25d5b8cbfda74140175))
* **pywire-language-server:** fix PyPI publish by using explicit build output dir ([8dec973](https://github.com/pywire/pywire/commit/8dec97382276ce0f139cc5abd89b0bd54806bc7d))
* **pywire-language-server:** trigger release PR update ([77491d0](https://github.com/pywire/pywire/commit/77491d02b5f51957b83b1ae3a320cbab53fb56a8))
* reduce bundle size ([ce632d0](https://github.com/pywire/pywire/commit/ce632d013e36e7ea24801509501486f58980cbde))
* rename to pywire ([44fb603](https://github.com/pywire/pywire/commit/44fb603f397a87e90b829b1203d8451624726676))
* resolve all test failures, xfails, and warnings in pywire core ([371286b](https://github.com/pywire/pywire/commit/371286b8627b375a8e7cce13e4e0a4dc71c14f8e))
* shadow doc write error ([fdba0c7](https://github.com/pywire/pywire/commit/fdba0c7bf72c5b5055d2d1bbbfcf07e967911d32))
* tsconfig to only scan src instead of only excludes ([22e9017](https://github.com/pywire/pywire/commit/22e9017077965577c905441f06467ca5e90d7ec1))
