---
title: Editor Setup
description: Configuring your editor for PyWire development.
---

PyWire provides first-class support for VS Code through our official extension.

## VS Code Extension

[Install to VS Code](vscode:extension/pywire.pywire) | [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=pywire.pywire)

The PyWire extension provides:
- Syntax highlighting for `.wire` files.
- IntelliSense for the Python block.
- Real-time error reporting.
- Go to definition and hover support.

To install:
1. Open VS Code.
2. Go to the Extensions view (`Ctrl+Shift+X`).
3. Search for "PyWire".
4. Click **Install**.

## Other Editors

Right now we only offer VS Code first-class support for editor extensions. While this may change down the line with demand, it is not currently in the roadmap. Creating integrations for other editors like [Neovim](https://neovim.io) and [Zed](https://zed.dev) should be relatively easy due to the official [Language Server](https://github.com/pywire/pywire-language-server), [Tree Sitter Grammar](https://github.com/pywire/tree-sitter-pywire), and [Prettier Plugin](https://github.com/pywire/prettier-plugin-pywire).