---
name: PyWire Language Server Guide
description: Architecture and development workflows for the PyWire LSP.
---

# PyWire Language Server (LSP) Guide

Located at: `packages/pywire-language-server/`

## Architecture

The LSP is built using `pygls` and provides language features for `.wire` files.

- **`src/pywire_language_server/server.py`**: Entry point, LSP server initialization, and all feature handlers (hover, completion, definition, references).
- **`src/pywire_language_server/transpiler.py`**: Transpiles `.wire` source to Python AST.
- **`src/pywire_language_server/sourcemap.py`**: Maps positions between `.wire` source and transpiled Python.
- **`src/pywire_language_server/ty.py`**: Integration with the `ty` type checker for diagnostics.

## Development Workflow

```bash
cd packages/pywire-language-server
uv run pytest          # Run tests
uv run ruff check .    # Lint
uv run ruff format .   # Format
uv run ty check .      # Type check
```

**Entry point**: `pywire-lsp` CLI command (defined in `pyproject.toml`) calls `pywire_language_server.server:start`.

**Integration**: Consumed by `vscode-pywire` via `lsp_launcher.py`.

## Self-Updating Rule

> [!IMPORTANT]
> If you make any substantial architectural changes, add new features, or modify the development workflow for `pywire-language-server`, you **MUST** update this `SKILL.md` file to reflect those changes accurately.
