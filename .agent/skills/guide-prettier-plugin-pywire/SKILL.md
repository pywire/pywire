---
name: Prettier Plugin PyWire Guide
description: Guide for the PyWire Prettier formatter plugin.
---

# Prettier Plugin PyWire Guide

This guide covers `prettier-plugin-pywire`, which handles code formatting for `.wire` files.

Located at: `packages/prettier-plugin-pywire/`

## 🏗️ Structure

- **`src/index.ts`**: Plugin entry point.
- **`src/parser.ts`**: Integrates with the PyWire parser.
- **`src/printer.ts`**: Logic for printing the Prettier AST back to source.
- **`src/utils/`**: Shared utilities.
- **`build.mjs`**: esbuild bundler script.

## 🛠️ Workflow

Uses **pnpm**:

```bash
cd packages/prettier-plugin-pywire
pnpm test       # Run vitest tests
pnpm check      # Full check: format, lint, typecheck, build
```

## 🔄 Self-Updating Rule

> [!IMPORTANT]
> If you modify the printing logic, add new formatting options, or change how the plugin integrates with Prettier in `prettier-plugin-pywire`, you **MUST** update this `SKILL.md` file.
