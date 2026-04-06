---
name: VS Code PyWire Guide
description: Development guide for the PyWire VS Code extension.
---

# VS Code PyWire Guide

This guide covers the `vscode-pywire` extension, the primary IDE integration for PyWire.

Located at: `packages/vscode-pywire/`

## Structure

- **`src/extension.ts`**: Main entry point for the extension.
- **`src/lsp_launcher.py`**: Python helper that spawns the language server.
- **`src/types/`**: TypeScript type definitions.
- **`package.json`**: Extension manifest (commands, views, configuration).
- **`language-configuration.json`**: Language settings (comments, brackets).
- **`syntaxes/`**: TextMate grammar for syntax highlighting.
- **`build.js`**: esbuild bundler script.

## Workflow

Uses **pnpm** (not npm):

```bash
cd packages/vscode-pywire
pnpm watch          # Compile on change (esbuild)
pnpm watch:tsc      # TypeScript type checking in watch mode
pnpm check          # Full check: format, lint, typecheck, build
```

**Debugging**: Use the "Run Extension" launch configuration in VS Code.

**LSP**: This extension spawns `pywire-language-server` via `lsp_launcher.py`.

## Self-Updating Rule

> [!IMPORTANT]
> If you add new commands, configuration settings, or change the extension lifecycle in `vscode-pywire`, you **MUST** update this `SKILL.md` file.
