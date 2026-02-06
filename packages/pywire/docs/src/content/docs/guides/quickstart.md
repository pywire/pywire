---
title: Quickstart
description: Get up and running with PyWire in seconds.
---

Welcome to PyWire! This guide will help you set up your first project instantly using our scaffolding tools.

## The Fastest Way: `create-pywire-app`

The easiest way to start a new project is using `uvx` to run our interactive scaffolding tool.

```sh
uvx create-pywire-app
```

This command will launch an interactive wizard that guides you through:

1. **Project Name**: Naming your new application.
2. **Template Selection**: Choosing a starter template (e.g., Counter, Blog, SaaS Starter).
3. **Routing Style**: Selecting between file-system based routing (like Svelte) or explicit routing (more like Flask/FastAPI).
4. **Configuration**: Setting up Git, VS Code extensions, and more.

Once the setup is complete, navigate into your new project directory:

```sh
cd my-pywire-app
```

## Installation Scripts

If you don't have `uv` installed yet, you can use our automated installation scripts to set up everything for you.

### macOS / Linux

```sh
curl -fsSL pywire.dev/install | sh
```

### Windows (PowerShell)

```powershell
irm pywire.dev/install.ps1 | iex
```

## Running the Development Server

To start your application in development mode, use the `pywire dev` command. This starts a high-performance server with hot-reloading and a live TUI dashboard.

```sh
pywire dev
```

Your app will be available at `http://localhost:3000`.

## What's Next?

* Check out the [Introduction](/docs/guides/introduction) to understand the core philosophy.
* Build your first component in the [Walkthrough](/docs/guides/your-first-component).
