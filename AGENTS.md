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

The dependency graph is **derived, not declared**: `python3 scripts/monorepo_graph.py` parses every `pyproject.toml` (plus a small side-table for `examples`/docs) and is the source of truth for floors, `ci.yml` fan-outs, and root orchestrator order.

- `check-floors` — every floor must be ≥ the latest **published** upstream version, and `_FLOORS` in the downstream `src/<pkg>/_compat.py` must equal the pyproject floor. Run it after touching any floor; it's also an always-on CI job.
- `check-ci` — `ci.yml` `if:` fan-outs must match the graph-derived sets (a job runs for its own package + all transitive upstream packages).
- `check-publishable <pkg>` — a release PR for `<pkg>` is mergeable only when every floor it declares is already published (upstream merged + published).
- `release-order [pkgs...]` — topological merge order for release PRs (auto-detects open `release-please--*` PRs with no args).
- `units` / `affected [base-ref]` — what the root orchestrators and `--changed` iterate.

When a downstream package starts using a new upstream feature, bump **both** in the same commit: the dep floor in the downstream `pyproject.toml` and `_FLOORS` in its `_compat.py` — `check-floors` tells you exactly what and where. CI (`check-monorepo-graph`) and the release-PR gate (`Release Floors Gate` status, set by `release.yml`) enforce both.

JS packages (`vscode-pywire`, `prettier-plugin-pywire`) don't depend on tree-sitter-pywire via npm; no floors there.

Import across packages only via published dependencies, never by folder path.

### Local tooling contract

Every checkable unit (each `packages/*`, `examples`, `docs`) **must** expose `scripts/check` = the full local gate (format, lint, types, generated-code staleness, tests), self-contained (`uv run --package <pkg> --extra dev …` — never assume the root venv). `scripts/lint` and `scripts/test` are optional granular entry points; orchestrators skip units that lack them. `check-scripts` verifies all of this.

Root `scripts/check|test|lint` iterate `monorepo_graph.py units` (topological); `scripts/check --changed [base-ref]` runs only affected units. `scripts/hooks/pre-git-check.sh` validates its unit mapping against the same graph.

## Worktrees & commit gate

Create git worktrees under `.worktrees/`. Tool-managed ones live in `.claude/worktrees/` (Claude Code) and `.pi/worktrees/` (pi-dynamic-workflows); all three are gitignored.

Agent-run `git commit` / `git push` goes through `scripts/hooks/pre-git-check.sh`, which runs `./scripts/check` for the affected packages and blocks on failure. Fix the reported errors; don't bypass it.

## Commits, PRs, releases

Releases are automated by release-please (one PR per package; merge it to publish to PyPI / npm / Marketplace). Never bump versions by hand.

- Conventional commits. Scopes: `pywire`, `pywire-auth`, `pywire-cli`, `pywire-language-server`, `pywire-parser`, `pywire-templates`, `tree-sitter-pywire`, `vscode-pywire`, `prettier-plugin-pywire`, `create-pywire-app`, `pywire-docs`.
- release-please attributes commits to packages by **file path**, not scope. To release a package, change a real file inside it. Never use `--allow-empty` (it attributes to every package).
- `chore:` commits are ignored by release-please — use for CI/infra/deps.
- PR titles must not contain parentheses beyond the scope: squash-merge appends ` (#NN)`, and an extra `(` makes release-please silently drop the commit. Put `Closes #N` in the body; use `feat!:` + a `BREAKING CHANGE:` footer for breaking changes.

Release ordering:
1. Feature PRs bump floors for any new upstream feature they use (same commit; `check-floors` verifies).
2. Merge release PRs upstream-first — `release-order` prints the order; the `Release Floors Gate` status check enforces it.
3. If the gate is red, the blocker is upstream: an unmerged release PR or a failed publish job — fix that, not the gate.

CI (`.github/workflows/ci.yml`) path-filters jobs per package; `check-ci` verifies the fan-outs match the graph.
