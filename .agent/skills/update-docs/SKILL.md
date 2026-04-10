---
name: Documentation Updater
description: Audit the docs site against current source code and update stale, stub, or missing documentation pages.
---

# Documentation Updater

Audits the PyWire documentation site (`docs/`) against the current source code and updates pages that are stale, thin, or missing. Run this after adding or changing framework features.

## Usage

```
/update-docs                          # Full audit + update
/update-docs reactivity               # Focus on a specific area
/update-docs --tutorial-only          # Only update tutorial steps
```

## Docs Site Structure

- **Site framework**: Astro + Starlight
- **Content directory**: `docs/src/content/docs/`
- **Sidebar config**: `docs/astro.config.mjs` (static sidebar definition)
- **Tutorial pages**: `docs/src/content/docs/tutorial/` (`.mdx` with special frontmatter)
- **Content schema**: `docs/src/content.config.ts`

### Content Sections

| Directory | Purpose |
|-----------|---------|
| `concepts/` | Core concepts (wire file, reactivity, events, components, context) |
| `syntax/` | Template syntax (interpolation, control flow, blocks, event modifiers) |
| `guides/` | How-to guides (quickstart, routing, layouts, forms, CLI, editor, deployment) |
| `reference/` | API reference (auto-generated sidebar) |
| `tutorial/` | Interactive tutorial steps |

### Frontmatter

**Regular pages** (`.md`):
```yaml
---
title: Page Title
description: One-line description.
---
```

**Tutorial pages** (`.mdx`):
```yaml
---
title: Step Title
tutorial: "Basic PyWire"
section: Section Name
description: One-line description.
files:
  - path: pages/index.wire
    initial: |
      ...starting code...
    solution: |
      ...correct answer...
successCriteria:
  - type: file_contains | browser_route_text | browser_element | file_exists
    description: "Human readable check"
    target: "file path or CSS selector"
    pattern: "regex pattern"
    route: "/"
pagesDir: pages
initialRoute: "/"
---
```

### Code Blocks

- `.wire` file examples: use ` ```pywire ` language hint
- Python code: use ` ```python ` or ` ```py `
- Shell commands: use ` ```sh `
- HTML snippets: use ` ```html `
- JSON config: use ` ```json `

## Workflow

### Step 1: Audit

Map the current source code features against existing documentation:

1. **Read public exports** from `packages/pywire/src/pywire/__init__.py`
2. **Read CLI commands** from `packages/pywire/src/pywire/cli/main.py`
3. **Read directives** from `packages/pywire/src/pywire/compiler/directives/`
4. **Read all doc pages** under `docs/src/content/docs/`
5. **Classify each feature** as: documented, stale, stub, or missing

### Step 2: Update

For each issue found:

- **Stale pages**: Cross-reference against source code, fix outdated APIs, code examples, and prose
- **Stub pages**: Expand with concept explanation, code examples, common patterns, and links to related pages
- **Missing pages**: Create new page with proper frontmatter, add to sidebar in `docs/astro.config.mjs`
- **Tutorial gaps**: Add new tutorial steps matching the exact `.mdx` frontmatter schema

### Step 3: Verify

```sh
cd docs && pnpm run build
```

Build must pass with zero errors before committing.

### Step 4: Format & Lint

```sh
cd docs && pnpm format && pnpm lint:fix
```

### Step 5: Commit

Use conventional commit prefixes:
- `docs(stale):` — fixing outdated content
- `docs(core):` — expanding core framework docs
- `docs(components):` — expanding component/layout docs
- `docs(cli):` — expanding CLI/tooling docs
- `docs(new):` — creating new pages
- `docs(tutorial):` — adding/updating tutorial steps
- `docs(polish):` — consistency fixes, broken links, formatting

## Key Source Code Locations

| Feature Area | Source Path |
|-------------|------------|
| Public API | `packages/pywire/src/pywire/__init__.py` |
| CLI commands | `packages/pywire/src/pywire/cli/main.py` |
| Directives | `packages/pywire/src/pywire/compiler/directives/` |
| Lifecycle hooks | `packages/pywire/src/pywire/runtime/page.py` (look for `LIFECYCLE_HOOKS`) |
| Ref system | `packages/pywire/src/pywire/core/refs.py` |
| Expose decorator | `packages/pywire/src/pywire/core/expose.py` |
| Props system | `packages/pywire/src/pywire/core/props.py` |
| Form validation | `packages/pywire/src/pywire/runtime/validation.py` |
| Built-in components | `packages/pywire/src/pywire/components/` |
| Event data types | `packages/pywire/src/pywire/runtime/event_data.py` |
| PyWire app class | `packages/pywire/src/pywire/app.py` |
| VS Code extension | `packages/vscode-pywire/package.json` |
| Language server | `packages/pywire-language-server/src/pywire_language_server/server.py` |
| Prettier plugin | `packages/prettier-plugin-pywire/` |
| Create-pywire-app | `packages/create-pywire-app/` |

## Important Rules

1. **Always read source code** before writing docs — don't guess at API signatures or behavior
2. **Don't modify** `docs/astro.config.mjs` beyond adding sidebar entries
3. **Don't modify** the tutorial step system (components in `docs/src/components/tutorial/`)
4. **Match existing tone** — concise, practical, code-first
5. **Run format & lint** before committing: `cd docs && pnpm format && pnpm lint:fix`
6. **Build must pass**: `cd docs && pnpm run build`
