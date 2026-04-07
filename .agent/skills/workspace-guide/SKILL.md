---
name: Workspace Overview
description: Git workflow, release process, key config files, and cross-package best practices for the PyWire monorepo.
---

# PyWire Monorepo Guide

Covers things not in CLAUDE.md: git/release workflow, key config files, and cross-package rules.

## Git Workflow

Standard git — no submodule steps. Use conventional commits scoped to the package:

- `feat(pywire): ...` — new feature in core
- `fix(pywire-language-server): ...` — bug fix in LSP
- `chore: ...` — maintenance tasks

## Releases

Fully automated via **Release Please**:
1. Merge conventional commits to `main`
2. Release Please opens a PR per package with version bumps and CHANGELOG
3. Merge the Release Please PR → GitHub Actions publishes to PyPI / npm / VS Code Marketplace

Each package is versioned independently (`separate-pull-requests: true`).

**Do not manually bump versions** in `pyproject.toml` or `package.json` — Release Please handles this.

## Key Config Files

- `pyproject.toml` — uv workspace root (members: all Python packages + examples)
- `pnpm-workspace.yaml` — pnpm workspace (members: JS/TS packages)
- `release-please-config.json` — per-package release configuration
- `.release-please-manifest.json` — current versions for each package
- `.github/workflows/ci.yml` — path-filtered CI per package
- `.github/workflows/release.yml` — Release Please + publish jobs

## Best Practices

- **Don't import across package boundaries** unless it's a published package dependency (e.g., LSP depends on the `pywire` package, not the folder path).
- **Root `scripts/`** delegate to per-package `scripts/` — actual build/test logic lives in each package's scripts.

## Running Demos

```bash
uv run python examples/demo-app/src/main.py
```
