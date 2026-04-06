---
name: Workspace Overview
description: High-level overview of the PyWire monorepo structure and development workflows.
---

# PyWire Monorepo Guide

This guide explains the structure and workflow for the **PyWire monorepo** (`pywire-monorepo`).

## Structure

| Path | Description |
|------|-------------|
| `packages/pywire/` | Core framework (Python + Rust extension) |
| `packages/pywire-language-server/` | LSP implementation |
| `packages/vscode-pywire/` | VS Code extension |
| `packages/create-pywire-app/` | Project initializer CLI |
| `packages/prettier-plugin-pywire/` | Prettier formatter plugin |
| `packages/tree-sitter-pywire/` | Tree-sitter grammar |
| `docs/site/` | Documentation site |
| `examples/` | Example applications |
| `scripts/` | Root orchestration scripts |
| `scratch/` | Scratchpad for experiments (gitignored) |

Python packages are managed as a **uv workspace** (root `pyproject.toml`). JS/TS packages are managed as a **pnpm workspace** (`pnpm-workspace.yaml`).

## Workflows

### Setup
```bash
git clone https://github.com/reecelikesramen/pywire-monorepo.git
cd pywire-monorepo
./scripts/install  # uv sync + pnpm install for all packages
```

### Checks
```bash
./scripts/check    # Runs lint/type/test for all packages
./scripts/test     # Runs test suites only
```

### Running Demos
```bash
uv run python examples/demo-app/src/main.py
```

### Git Workflow
Standard git — no submodule steps. Commit directly to the relevant package path. Use conventional commits for all changes:

- `feat(pywire): ...` — new feature in core
- `fix(pywire-language-server): ...` — bug fix in LSP
- `chore: ...` — maintenance tasks

### Releases
Releases are fully automated via **Release Please**:
1. Merge conventional commits to `main`
2. Release Please opens a PR per package with version bumps and CHANGELOG
3. Merge the Release Please PR → GitHub Actions publishes to PyPI / npm / VS Code Marketplace

Each package is versioned independently (`separate-pull-requests: true`).

## Key Files

- `pyproject.toml` — uv workspace root (members: all Python packages + examples)
- `pnpm-workspace.yaml` — pnpm workspace (members: JS/TS packages)
- `release-please-config.json` — per-package release configuration
- `.release-please-manifest.json` — current versions for each package
- `.github/workflows/ci.yml` — path-filtered CI per package
- `.github/workflows/release.yml` — Release Please + publish jobs

## Best Practices

- **Don't import across package boundaries** unless it's a published package dependency (e.g., LSP depends on the `pywire` package, not the folder path).
- **Root `scripts/`** delegate to per-package `scripts/` — actual build/test logic lives in each package's scripts.
- **Versions**: Do not manually bump versions in `pyproject.toml` or `package.json` — Release Please handles this via conventional commits.
