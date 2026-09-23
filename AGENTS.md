# AGENTS.md

PyWire is an HTML-over-the-wire Python web framework. This is a polyglot monorepo:
**uv** workspace for Python packages, **pnpm** workspace for JS/TS packages.

## Setup & commands

```sh
./scripts/install   # uv sync + pnpm install + build TS client into packages/pywire/src/pywire/client/
./scripts/check     # format/lint/typecheck/tests across packages
./scripts/test      # tests for every Python package (+ core client TS)
```

Every package has `./scripts/check`; Python packages also have `./scripts/test`. Run them from the package dir.
Single test: `uv run --package <pkg> pytest tests/path/test_x.py::test_name` (core needs `--extra dev`; pywire-auth needs `--extra sqlalchemy --extra dev`).

Tooling: Python → ruff format / ruff check / **ty** (not mypy) / pytest (+ nox for multi-version in core, LSP, create-pywire-app). TS → prettier / eslint / tsc / vitest. Use **pnpm**, never npm.

## Packages

| Path | What | Notes |
|------|------|-------|
| `packages/pywire` | Core framework (Starlette) + TS client in `src/pywire/client/` | App class: `runtime/app.py`. Built client assets ship in the wheel. `pywire` script is a shim to `pywire-cli`. |
| `packages/pywire-parser` | `.wire` parser + analysis (py-tree-sitter) | `pywire.compiler.{parser,ast_nodes,exceptions}` re-export from here. |
| `packages/pywire-cli` | `pywire` CLI: dev, run, build, deploy, check | Entry: `pywire_cli.main:cli`. |
| `packages/pywire-templates` | Shared Jinja2 deploy templates | Used by pywire-cli and create-pywire-app. |
| `packages/pywire-auth` | Auth providers (OIDC, local IdP) + identity stores | Core auth primitives live in `pywire.auth`. |
| `packages/pywire-language-server` | LSP (pygls) | `.wire` → Python transpile + sourcemap, `ty` diagnostics. |
| `packages/create-pywire-app` | Scaffolding CLI | Try it: `uv run create-pywire-app` (`USE_LOCAL_PYWIRE=1` for local core). Templates: skeleton, counter, blog, saas. |
| `packages/tree-sitter-pywire` | Grammar for `.wire` | Edit `grammar.js` only; `src/` is generated (`pnpm exec tree-sitter generate`) and committed. `./scripts/check` fails if it is stale. |
| `packages/vscode-pywire` | VS Code extension | Spawns the LSP from `src/lsServerManager.ts`. Debug via "Run Extension" launch config. |
| `packages/prettier-plugin-pywire` | Prettier formatter for `.wire` | vitest. |
| `docs/` | Astro + Starlight docs site with Pyodide tutorial | `pnpm build` must pass. See `update-docs` skill. |
| `examples/` | Demo apps (uv workspace members) | |

`.wire` files embed Python, HTML, CSS and JS; the grammar, parser, LSP, formatter and extension all exist to support them.

## Framework conventions

- **Transport-agnostic.** Middleware, auth and sessions must behave identically for HTTP loads and WebSocket SPA navigations. Never make app developers handle the two contexts differently (no Blazor-style explicit auth scopes / cascading parameters).
- **Events vs callbacks.** `@event={handler}` is for DOM events only (modifiers like `.prevent`, field masks). Component callbacks are plain props named `on_*` typed `EventHandler[...]`, e.g. `<Form on_submit={handler} />`.
- **Debug logging.** `PYWIRE_LOG_LEVEL=DEBUG` enables internal framework logs. `PyWire(debug=True)` is app-developer UX only (error pages, stack traces, source endpoints) and also un-silences the client `Logger`.

## Code policy

The project has few users. Prefer clean breaks over compatibility:
- Delete dead code immediately — no commented-out code, no `@deprecated` unless asked.
- Change APIs directly and update all internal callers; no forwarding shims.
- Keep tests and current features passing.

Verify by running code rather than guessing: throwaway scripts go in `scratch/` (gitignored) — see the `scratchpad` skill. If one proves a real regression or requirement, port it into the package's `tests/`.

## Cross-package version floors

Dependency chains: `tree-sitter-pywire` → `pywire-parser` → `pywire[build]` / `pywire-language-server`; `pywire-cli` → `pywire[build]`, `pywire-templates`; `pywire-auth` → `pywire`; `create-pywire-app` → `pywire-templates`.

When a downstream package starts using a new upstream feature, bump **both** in the same commit:
1. the dep floor in the downstream `pyproject.toml` (e.g. `pywire-parser>=0.6.0`), and
2. `_FLOORS` in the downstream `src/<package>/_compat.py` (runtime guard for stale venvs).

JS packages (`vscode-pywire`, `prettier-plugin-pywire`) don't depend on tree-sitter-pywire via npm; no floors there.

Import across packages only via published dependencies, never by folder path.

## Commits, PRs, releases

Releases are automated by release-please (one PR per package; merge it to publish to PyPI / npm / Marketplace). Never bump versions by hand.

- Conventional commits. Scopes: `pywire`, `pywire-auth`, `pywire-cli`, `pywire-language-server`, `pywire-parser`, `pywire-templates`, `tree-sitter-pywire`, `vscode-pywire`, `prettier-plugin-pywire`, `create-pywire-app`, `pywire-docs`.
- release-please attributes commits to packages by **file path**, not scope. To release a package, change a real file inside it. Never use `--allow-empty` (it attributes to every package).
- `chore:` commits are ignored by release-please — use for CI/infra/deps.
- PR titles must not contain parentheses beyond the scope: squash-merge appends ` (#NN)`, and an extra `(` makes release-please silently drop the commit. Put `Closes #N` in the body; use `feat!:` + a `BREAKING CHANGE:` footer for breaking changes.

CI (`.github/workflows/ci.yml`) path-filters jobs per package.
