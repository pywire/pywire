# pywire

**HTML-over-the-wire Python web framework.**

Build reactive web apps in pure Python — no JavaScript required. PyWire renders HTML on the server and pushes updates over WebSocket, giving you the reactivity of a SPA without writing a line of frontend code.

```sh
uvx create-pywire-app
```

> **Documentation:** [pywire.dev/docs](https://pywire.dev/docs)

---

## What's in this repo

This is the PyWire monorepo. All packages are developed and released from here.

| Package | Description | PyPI / Marketplace |
|---------|-------------|-------------------|
| [`packages/pywire`](packages/pywire) | Core framework — Starlette-based runtime, `.wire` compiler, CLI | [![PyPI](https://img.shields.io/pypi/v/pywire)](https://pypi.org/project/pywire/) |
| [`packages/pywire-auth`](packages/pywire-auth) | Authentication — OAuth2/OIDC providers, local IdP, policies, live auth | [![PyPI](https://img.shields.io/pypi/v/pywire-auth)](https://pypi.org/project/pywire-auth/) |
| [`packages/pywire-language-server`](packages/pywire-language-server) | LSP server for `.wire` files (completions, diagnostics, hover) | [![PyPI](https://img.shields.io/pypi/v/pywire-language-server)](https://pypi.org/project/pywire-language-server/) |
| [`packages/create-pywire-app`](packages/create-pywire-app) | Project scaffolding CLI — `uvx create-pywire-app` | [![PyPI](https://img.shields.io/pypi/v/create-pywire-app)](https://pypi.org/project/create-pywire-app/) |
| [`packages/vscode-pywire`](packages/vscode-pywire) | VS Code extension — syntax highlighting, LSP integration | [![VS Code](https://img.shields.io/visual-studio-marketplace/v/pywire.vscode-pywire)](https://marketplace.visualstudio.com/items?itemName=pywire.vscode-pywire) |
| [`packages/prettier-plugin-pywire`](packages/prettier-plugin-pywire) | Prettier formatter for `.wire` files | [![npm](https://img.shields.io/npm/v/prettier-plugin-pywire)](https://www.npmjs.com/package/prettier-plugin-pywire) |
| [`packages/tree-sitter-pywire`](packages/tree-sitter-pywire) | Tree-sitter grammar for `.wire` syntax | [![crates.io](https://img.shields.io/crates/v/tree-sitter-pywire)](https://crates.io/crates/tree-sitter-pywire) |
| [`docs`](docs) | Documentation site — [pywire.dev/docs](https://pywire.dev/docs) | — |

---

## Quick start

You need [uv](https://docs.astral.sh/uv/) installed.

```sh
uvx create-pywire-app   # scaffold a new project
cd my-app
uv run pywire dev       # start dev server with hot reload
```

Or with the installer script (handles uv setup too):

```sh
# macOS / Linux
curl -fsSL pywire.dev/install | sh

# Windows (PowerShell)
irm pywire.dev/install.ps1 | iex
```

---

## How it works

PyWire pages are `.wire` files — a template format that embeds Python, HTML, CSS, and even JS in a single file:

```wire
---
count = wire(0)

def increment(self):
    self.count += 1

---
<button @click="increment">
    Clicked {{ count }} times
</button>
```

- **Server renders HTML** on initial load and after every event
- **WebSocket pushes diffs** back to the browser — no full page reloads
- **`wire()` variables** are reactive — changing them triggers a re-render of affected regions
- **`.wire` files** are compiled to Python at startup; the Rust parser (tree-sitter) handles the custom syntax

---

## Development setup

This repo uses **uv** for Python packages and **pnpm** for Node packages.

```sh
./scripts/install   # uv sync + pnpm install + build TypeScript client
./scripts/check     # format check + type-check + test across all packages and supported versions
./scripts/test      # run core Python + client TypeScript tests
./scripts/lint      # run the formatter across all projects
```

---

## Contributing

- PRs require **squash merge** and **1 approving review**
- All relevant CI checks must pass before merge
- Follow [Conventional Commits](https://www.conventionalcommits.org/) — releases are automated via `release-please`
- Valid scopes: `pywire`, `pywire-language-server`, `tree-sitter-pywire`, `vscode-pywire`, `prettier-plugin-pywire`, `create-pywire-app`, `pywire-docs`

---

## Support

If PyWire is helping you build, consider supporting the project. Donations cover documentation hosting, CI/CD, and development time.

[![GitHub Sponsor](https://img.shields.io/badge/Sponsor-pywire-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/pywire)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-reecelikesramen-ff5e5b?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/reecelikesramen)
