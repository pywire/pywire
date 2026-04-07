---
name: Create PyWire App Guide
description: Development guide for the PyWire project initializer CLI.
---

# Create PyWire App Guide

Located at: `packages/create-pywire-app/`

## Structure

- **`src/create_pywire_app/main.py`**: All CLI logic — argument parsing, interactive prompts (`questionary`), `ProjectGenerator`, and `TemplateRenderer`.
- **`src/create_pywire_app/templates/`**: Jinja2 templates organized by template name and routing strategy.
  - `common/` — shared files: `pyproject.toml.j2`, `main-path.py.j2`, `main-explicit.py.j2`, `README.md.j2`, `Dockerfile`, `render.yaml.j2`, `.gitignore`, `__error__.wire`, `extensions.json`
  - `skeleton/`, `counter/`, `blog/`, `saas/` — template-specific `.wire` and `.wire.j2` files, split into `path-based/` and `explicit/` subdirectories

## Interactive Prompts

The CLI asks users:
1. **Project location** — filesystem path (default: `./my-pywire-app`)
2. **Template** — `skeleton`, `counter`, `blog` (Markdown + SQLite), or `saas` (Stripe + SQLAlchemy + auth stub)
3. **Routing strategy** — `path-based` (file-system routing, `__layout__.wire`) or `explicit` (manually registered pages)
4. **Use `src/` layout?** — wraps `pages/` under `src/`
5. **Deployment adapters** — Docker (`Dockerfile`) and/or Render (`render.yaml`)

After generation it runs `uv sync` and optionally starts `pywire dev`.

## CLI Flags

- `--pywire-version <ver>` — pin a specific pywire version in the generated `pyproject.toml`
- `USE_LOCAL_PYWIRE=1` env var — uses a local path dependency (hardcoded workspace path, for local dev/testing only)

## Template Dependencies

| Template | Extra dependencies added to `pyproject.toml` |
|----------|----------------------------------------------|
| blog     | `markdown>=3.6`                              |
| saas     | `stripe>=7.0.0`, `sqlalchemy>=2.0.0`        |

## Development Workflow

Test by running the CLI directly:

```bash
cd packages/create-pywire-app
uv run create-pywire-app
```

Or with a local pywire build:

```bash
USE_LOCAL_PYWIRE=1 uv run create-pywire-app
```

## Self-Updating Rule

> [!IMPORTANT]
> If you add new templates, change CLI prompts/flags, or modify the project generation logic, update this `SKILL.md` file.
