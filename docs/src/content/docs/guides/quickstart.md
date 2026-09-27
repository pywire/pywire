---
title: Quickstart
description: Get up and running with PyWire in seconds.
---

Welcome to PyWire! This guide will help you set up your first project instantly using our scaffolding tools.

## Create a project

Run one of these. They all launch the same interactive wizard, so pick whichever tool you already have.

**With uv** (recommended):

```sh
uvx create-pywire-app
```

**With Node.js** (installs [uv](https://docs.astral.sh/uv/) for you if it's missing):

```sh
npx create-pywire-app
```

**With neither**, the install script sets up uv and then launches the wizard:

```sh
curl -fsSL https://pywire.dev/install | sh
```

On Windows, use PowerShell instead:

```powershell
irm https://pywire.dev/install.ps1 | iex
```

The wizard guides you through:

1. **Project Name**: Naming your new application.
2. **Template Selection**: Choosing a starter template (e.g., Counter, Blog, SaaS Starter).
3. **Routing Style**: Selecting between file-system based routing (like Svelte) or explicit routing (more like Flask/FastAPI).
4. **Configuration**: Setting up Git, VS Code extensions, and more.

It then installs pywire into the new project. Once it finishes, move into the project directory:

```sh
cd my-pywire-app
```

## Running the Development Server

To start your application in development mode, use the `pywire dev` command. This starts a high-performance server with hot-reloading and a live TUI dashboard.

```sh
uv run pywire dev
```

Your app will be available at `http://localhost:3000`.

## What's Next?

- Check out the [Introduction](/docs/guides/introduction) to understand the core philosophy.
- Build your first component in the [Walkthrough](/docs/guides/your-first-component).
