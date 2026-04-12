# PyWire for Visual Studio Code

Full IDE support for [PyWire](https://pywire.dev) — an HTML-over-the-wire Python web framework built on Starlette. Provides syntax highlighting, formatting, and language intelligence for `.wire` files.

## What is PyWire?

PyWire lets you build reactive web UIs in Python using a custom template format (`.wire` files). Each file is a self-contained component that combines Python logic, HTML structure, and optional embedded CSS and JavaScript — no JavaScript framework required.

```wire
---
count = wire(0)

---
<button @click={count.value += 1}">Clicked {count} times</button>
```

## Features

### Syntax Highlighting

Full syntax highlighting for `.wire` files, with embedded language support for each section:

- **Python** — logic block between `---` fences
- **HTML** — template markup with PyWire expressions and directives
- **CSS** — inside `<style>` blocks
- **JavaScript** — inside `<script>` blocks

### Language Intelligence

Powered by the [PyWire Language Server](https://github.com/pywire/pywire), the extension provides:

- **Completions** — context-aware suggestions for Python, HTML attributes, CSS properties, and JS
- **Hover documentation** — type info and docstrings on hover
- **Go to definition** — navigate to symbols across Python, CSS, and JS
- **Find references** — locate all usages of a symbol
- **Rename** — rename symbols across embedded languages
- **Signature help** — function argument hints as you type
- **Document highlights** — highlight all occurrences of the symbol under the cursor

Embedded `<script>` and `<style>` blocks receive full JS and CSS language support from VS Code's built-in language services.

### Formatting

`.wire` files are formatted with [Prettier](https://prettier.io) via the `prettier-plugin-pywire` formatter. Format on save is enabled by default — no configuration needed.

To format manually: **Format Document** (`Shift+Alt+F`).

### Smart Comment Toggling

`Cmd+/` (macOS) or `Ctrl+/` (Windows/Linux) toggles comments based on which section the cursor is in:

- **Python block** → `# line comment`
- **HTML template** → `<!-- block comment -->`

### Dev Server Integration

Start and stop the PyWire dev server directly from the editor. When a `.wire` file is open, a **▶ Run Dev Server** button appears in the editor title bar. Clicking it opens a terminal and runs `uv run pywire dev --no-tui`. The button switches to **■ Stop Dev Server** while the server is running.

### Update Notifications

The extension periodically checks for newer versions of PyWire and prompts you to upgrade. To upgrade manually, run the **PyWire: Attempt Upgrade** command from the Command Palette.

## Requirements

- [Python extension for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-python.python) — used to detect your active Python interpreter
- PyWire installed in your Python environment:

  ```sh
  uv add pywire
  # or
  pip install pywire
  ```

The language server (`pywire-language-server`) is installed automatically as part of PyWire.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `pywire.pythonPath` | `"python3"` | Path to the Python interpreter used to launch the language server. Defaults to the interpreter selected in the Python extension. |
| `pywire.tyPath` | *(auto)* | Path to the [`ty`](https://github.com/astral-sh/ty) type checker executable. Defaults to `ty` on `PATH`. |
| `pywire.disableUpdateNotifications` | `false` | Disable periodic checks for PyWire updates. |
| `pywire.trace.server` | `"off"` | Trace LSP communication between VS Code and the language server. Set to `"messages"` or `"verbose"` for debugging. |

Settings can be adjusted in **Settings** (`Cmd+,`) under **Extensions → PyWire**, or directly in your `settings.json`:

```json
{
  "pywire.pythonPath": "/path/to/.venv/bin/python"
}
```

## Commands

All commands are available from the Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`):

| Command | Description |
|---|---|
| **PyWire: Run Dev Server** | Start the PyWire dev server in a terminal |
| **PyWire: Stop Dev Server** | Stop the running dev server |
| **PyWire: Restart Language Server** | Restart the language server (useful after installing packages) |
| **PyWire: Attempt Upgrade** | Upgrade PyWire to the latest version |
| **PyWire: Open Docs** | Open the PyWire documentation site |
| **PyWire: Open Docs (Nightly)** | Open the nightly documentation site |
| **PyWire: Toggle Comment** | Toggle a context-aware comment on the selected lines |

## Troubleshooting

**Language server not starting** — Make sure PyWire is installed in the Python environment selected in the Python extension. Run **PyWire: Restart Language Server** after installing.

**Wrong interpreter** — Set `pywire.pythonPath` explicitly to your virtual environment's Python binary (e.g. `/path/to/.venv/bin/python`).

**Seeing LSP errors** — Set `pywire.trace.server` to `"verbose"` and check the **PyWire** output channel (`View → Output → PyWire`) for details.

---

<!-- SUPPORT_MESSAGE_TEMPLATE_START -->
## ❤️ Support pywire

If pywire is helping you build, consider supporting the project. Donations cover documentation hosting, CI/CD runners, and the caffeine required for development.

[![GitHub Sponsor](https://img.shields.io/badge/Sponsor-pywire-ea4aaa?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/pywire)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-reecelikesramen-ff5e5b?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/reecelikesramen)

### Why sponsor?
* 🚀 Faster development of the core framework.
* 📖 Better docs and community examples.
* 🔧 Integration research.
<!-- SUPPORT_MESSAGE_TEMPLATE_END -->
