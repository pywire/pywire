# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

PyWire is an HTML-over-the-wire Python web framework. This monorepo is a **hybrid polyglot** setup managed by two package managers:
- **UV** — Python packages (core framework, language server, CLI tool, examples)
- **pnpm** — Node.js packages (VSCode extension, Prettier plugin, Tree-sitter grammar, client library, docs site)

## Setup

```sh
./scripts/install
```

This syncs the UV workspace (`uv sync`), installs pnpm workspace dependencies, and builds the TypeScript client assets inside `packages/pywire/src/pywire/client/`.

## Commands

### Workspace-wide

```sh
./scripts/check    # Full validation across all packages + tests
./scripts/lint     # Lint all packages
./scripts/test     # Run PyWire core tests (Python + client TS)
```

### packages/pywire (core)

```sh
cd packages/pywire
./scripts/check                            # ruff format/lint, ty, client TS checks, nox
./scripts/test                             # pytest --cov=pywire + pnpm test (client)
uv run --extra dev pytest tests/path/to/test_file.py::test_name  # single test
uv run --extra dev nox                     # multi-version Python tests
cargo clippy -- -D warnings && cargo fmt --check  # Rust checks
```

### packages/pywire-language-server

```sh
cd packages/pywire-language-server
./scripts/check    # ruff format/lint, ty, nox
./scripts/test     # pytest --cov=pywire_language_server
uv run pytest tests/path/to/test.py::test_name  # single test
```

### packages/create-pywire-app

```sh
cd packages/create-pywire-app
./scripts/check    # nox, ruff format, ty
./scripts/test     # pytest
```

### packages/prettier-plugin-pywire

```sh
cd packages/prettier-plugin-pywire
./scripts/check    # prettier, eslint, tsc, vitest
pnpm test          # vitest run
```

### packages/vscode-pywire

```sh
cd packages/vscode-pywire
./scripts/check    # prettier format check, eslint, tsc (no runtime tests)
```

### packages/tree-sitter-pywire

```sh
cd packages/tree-sitter-pywire
cargo test
tree-sitter test
```

## Architecture

### Package Layout

```
docs/                         # Interactive documentation site (Astro + Starlight + Pyodide)
packages/
  pywire/                     # Core Python framework (Python + Rust + TS client)
  pywire-language-server/     # LSP server (Python, pygls)
  create-pywire-app/          # Project scaffolding CLI (Python)
  vscode-pywire/              # VS Code extension (TypeScript)
  prettier-plugin-pywire/     # Prettier formatter for .wire files (TypeScript)
  tree-sitter-pywire/         # Tree-sitter grammar for .wire syntax (Rust)
examples/
  demo-app/
  demo-components/
  demo-routing/
```

### packages/pywire — Core Framework

The core package has three layers built together:

1. **Rust parser** (`Cargo.toml`, `src/`) — compiles to `pywire._pywire_parser` Python extension module via Maturin + PyO3. Uses tree-sitter-pywire for parsing `.wire` files.
2. **Python framework** (`src/pywire/`) — Starlette-based web framework. CLI entry point is `pywire` → `pywire.cli.main:cli`.
3. **TypeScript client** (`src/pywire/client/`) — pnpm workspace package. Built assets are included in the PyPI wheel via Maturin's `include` directive (along with `src/pywire/static/` and `src/pywire/templates/`).

Because the Rust extension is built by Maturin, `maturin develop` or the standard `uv sync` + `./scripts/install` flow is needed for a working dev environment. The Python module `pywire._pywire_parser` is intentionally excluded from type checking.

### .wire Files

`.wire` files are the framework's template format — a custom syntax embedding Python, HTML, CSS, and JS. Parsing is handled by the Rust/tree-sitter layer. The Tree-sitter grammar, Prettier plugin, and VS Code extension all exist to support this file type.

### Type Checking

Python type checking uses **ty** (not mypy). Tests and certain internal modules have broad rule suppressions in `pyproject.toml` — this is intentional.

### Tooling Quick Reference

| Language | Format | Lint | Type Check | Test |
|----------|--------|------|------------|------|
| Python | ruff format | ruff check | ty | pytest / nox |
| TypeScript | prettier | eslint | tsc | vitest / playwright |
| Rust | cargo fmt | cargo clippy | — | cargo test |

Multi-version Python testing uses **nox** in the core and language server packages.

### CI

GitHub Actions workflows use `dorny/paths-filter` to run checks only for packages that have changed. Release management uses `release-please` with per-package versioning.
