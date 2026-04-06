---
name: Tree-sitter PyWire Guide
description: Development guide for the Tree-sitter grammar for PyWire.
---

# Tree-sitter PyWire Guide

This guide covers the `tree-sitter-pywire` module, which defines the syntax for `.wire` files.

## 🏗️ Structure

- **`grammar.js`**: The main grammar definition.
- **`src/`**: Generated parser code (do not edit directly).
- **`queries/`**: Tree-sitter queries for highlighting, folds, and injections.
- **`test/`**: Corpus tests for the grammar.

Located at: `packages/tree-sitter-pywire/`

## 🛠️ Workflow

```bash
cd packages/tree-sitter-pywire
npx tree-sitter generate   # Regenerate src/ from grammar.js
npx tree-sitter test       # Run corpus tests in test/
```

## 🔄 Self-Updating Rule

> [!IMPORTANT]
> If you modify the grammar structure, add new nodes, or change the build/test workflow for `tree-sitter-pywire`, you **MUST** update this `SKILL.md` file.
