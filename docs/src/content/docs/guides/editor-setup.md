---
title: Editor Setup
description: Configuring your editor for PyWire development.
---

PyWire provides first-class support for VS Code through our official extension, backed by a Language Server Protocol (LSP) server, Tree-sitter grammar, and Prettier plugin.

## VS Code Extension

[Install to VS Code](vscode:extension/pywire.pywire) | [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=pywire.pywire)

The PyWire extension provides:

- **Syntax highlighting** for `.wire` files (HTML, Python, CSS, and directives)
- **IntelliSense** for the Python block — completions, signatures, and type information
- **Real-time diagnostics** — errors and warnings as you type
- **Go to definition** — jump to component definitions, imported modules, and wire variables
- **Hover information** — see type information and documentation on hover
- **Auto-formatting** — format `.wire` files on save via the Prettier plugin

To install:

1. Open VS Code.
2. Go to the Extensions view (`Ctrl+Shift+X`).
3. Search for "PyWire".
4. Click **Install**.

### Recommended Settings

For the best experience, add these to your VS Code `settings.json`:

```json
{
  "[pywire]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true
  }
}
```

**Extension settings:**

| Setting                             | Description                                                                  |
| ----------------------------------- | ---------------------------------------------------------------------------- |
| `pywire.pythonPath`                 | Path to the Python interpreter (auto-detected by default)                    |
| `pywire.tyPath`                     | Path to the `ty` type checker binary                                         |
| `pywire.trace.server`               | Trace level for language server communication (`off`, `messages`, `verbose`) |
| `pywire.disableUpdateNotifications` | Suppress extension update notifications                                      |

## Language Server

The PyWire Language Server powers the IntelliSense features in the VS Code extension. It's built on [pygls](https://github.com/openlawlibrary/pygls) and implements the Language Server Protocol, so it can work with any LSP-compatible editor.

The language server provides:

- **Python completions** inside script blocks — aware of `wire`, `derived`, `effect`, `props`, and other PyWire APIs
- **Template completions** — directive names (`$if`, `$for`, `$show`), event handlers (`@click`, `@input`), and component tags
- **Diagnostics** — syntax errors, undefined variables, and type mismatches
- **Hover information** — documentation for directives, attributes, and Python objects

## Prettier Plugin

The [Prettier Plugin for PyWire](https://github.com/pywire/prettier-plugin-pywire) auto-formats `.wire` files, handling the mixed HTML/Python/CSS syntax correctly.

Install it alongside Prettier:

```sh
pnpm add -D prettier prettier-plugin-pywire
```

Add it to your `.prettierrc`:

```json
{
  "plugins": ["prettier-plugin-pywire"]
}
```

## Tree-sitter Grammar

The [Tree-sitter grammar for PyWire](https://github.com/pywire/tree-sitter-pywire) provides syntax highlighting for any editor that supports Tree-sitter (Neovim, Helix, Zed, and others).

## Other Editors

The VS Code extension is the primary supported editor integration. However, the Language Server, Tree-sitter grammar, and Prettier plugin are all standalone packages. Any editor that supports LSP, Tree-sitter, or Prettier can integrate with PyWire:

- **Neovim**: Use the Tree-sitter grammar for highlighting and configure the language server via `lspconfig`
- **Zed**: Tree-sitter support built in; add the grammar to your configuration
- **Helix**: Native Tree-sitter support; configure the language server for full IntelliSense
