---
title: Quickstart
description: Get up and running with PyWire in seconds.
---

Welcome to PyWire! This guide will help you set up your first project instantly using our scaffolding tools.

## The Fastest Way: `create-pywire-app`

The recommended way to start a new project is using `uvx` (part of the [uv](https://github.com/astral-sh/uv)) package manager to run our interactive scaffolding tool.

```bash
uvx create-pywire-app
```

This command will launch an interactive wizard that guides you through:

1. **Project Name**: Naming your new application.
2. **Template Selection**: Choosing a starter template (e.g., Counter, Blog, SaaS Starter).
3. **Routing Style**: Selecting between file-system based routing (like Next.js) or explicit routing (like Flask/FastAPI).
4. **Configuration**: Setting up Git, VS Code extensions, and more.

Once the setup is complete, navigate into your new project directory:

```bash
cd my-pywire-app
```

## Running the Development Server

To start your application in development mode, use the `pywire dev` command. This starts a high-performance server with hot-reloading and a live TUI dashboard.

```bash
pywire dev
```

Your app will be available at `http://localhost:3000`.

## Installation Scripts (No `uv`?)

If you don't have `uv` installed yet, you can use our automated installation scripts to set up everything for you.

### macOS / Linux

```bash
curl -fsSL pywire.dev/install | sh
```

### Windows (PowerShell)

```powershell
irm pywire.dev/install.ps1 | iex
```

## What's Next?

* Check out the [Introduction](/docs/guides/introduction) to understand the core philosophy.
* Build your first component in the [Walkthrough](/docs/guides/your-first-component).
