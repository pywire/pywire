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
```

### packages/pywire-auth

```sh
cd packages/pywire-auth
uv run --extra sqlalchemy --extra dev pytest -q  # test suite (SQLAlchemy store included)
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
  pywire/                     # Core Python framework (Python + TS client)
  pywire-parser/              # Shared .wire file parser (Python, py-tree-sitter)
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

The core package has two layers built together:

1. **Python framework** (`src/pywire/`) — Starlette-based web framework. CLI entry point is `pywire` → `pywire.cli.main:cli`. Parsing is handled by the separate `pywire-parser` package (which uses `tree-sitter-pywire` via py-tree-sitter).
2. **TypeScript client** (`src/pywire/client/`) — pnpm workspace package. Built assets are included in the PyPI wheel via Hatchling's build config (along with `src/pywire/static/` and `src/pywire/templates/`).

### .wire Files

`.wire` files are the framework's template format — a custom syntax embedding Python, HTML, CSS, and JS. Parsing is handled by the `pywire-parser` package (pure Python, using py-tree-sitter + `tree-sitter-pywire`). The Tree-sitter grammar, Prettier plugin, and VS Code extension all exist to support this file type.

### Type Checking

Python type checking uses **ty** (not mypy). Tests and certain internal modules have broad rule suppressions in `pyproject.toml` — this is intentional.

### Tooling Quick Reference

| Language | Format | Lint | Type Check | Test |
|----------|--------|------|------------|------|
| Python | ruff format | ruff check | ty | pytest / nox |
| TypeScript | prettier | eslint | tsc | vitest / playwright |

Multi-version Python testing uses **nox** in the core and language server packages.

### CI

GitHub Actions workflows use `dorny/paths-filter` to run checks only for packages that have changed. Release management uses `release-please` with per-package versioning.

### Commit Conventions (release-please)

release-please uses **file paths only** to attribute commits to packages. The conventional commit scope (e.g., `fix(pywire):`) does NOT control which package gets a release PR — it only affects changelog formatting.

Rules:
- **Never use empty commits** (`--allow-empty`) to trigger releases — they fan out to ALL packages
- To bump a specific package, modify a file inside that package's directory (e.g., touch a docstring, add a changelog note)
- Use `chore:` prefix for CI/infra/dependency changes — release-please ignores `chore:` commits entirely
- Valid component scopes: `pywire`, `pywire-auth`, `pywire-language-server`, `tree-sitter-pywire`, `vscode-pywire`, `prettier-plugin-pywire`, `create-pywire-app`, `pywire-docs`
