---
name: Create PyWire App Guide
description: Development guide for the PyWire project initializer.
---

# Create PyWire App Guide

This guide covers `create-pywire-app`, the CLI tool for scaffolding new PyWire projects.

## 🏗️ Structure

- **`src/create_pywire_app/main.py`**: Command-line interface logic.
- **`templates/`**: Project templates (e.g., `default`, `minimal`).

## 🛠️ Workflow

1. **Test**: Run the CLI locally to verify project generation.
2. **Templates**: When updating the core framework, ensure templates remain compatible.

## 🔄 Self-Updating Rule

> [!IMPORTANT]
> If you add new templates, change CLI flags, or modify the bootstrapping process in `create-pywire-app`, you **MUST** update this `SKILL.md` file.
