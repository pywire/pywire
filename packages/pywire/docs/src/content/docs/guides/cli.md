---
title: CLI Reference
description: Comprehensive guide to the pywire command-line interface.
---

The `pywire` CLI is your primary tool for developing, building, and serving applications.

## Global Flags

* `--help`: Show help message and exit.
* `--version`: Show the version number.

## `pywire dev`

Starts the development server.

```bash
pywire dev [APP] [OPTIONS]
```

* **APP**: The application string (e.g., `main:app`). Optional if `main.py` or `app.py` exists.

**Options:**

* `--host TEXT`: Bind host (default: `127.0.0.1`).
* `--port INTEGER`: Bind port (default: `3000`).
* `--ssl-keyfile TEXT`: Path to SSL key file.
* `--ssl-certfile TEXT`: Path to SSL certificate file.
* `--env-file TEXT`: Path to .env file.
* `--no-tui`: Disable the Terminal User Interface and output standard logs.

### The TUI Dashboard

Running `dev` opens a rich dashboard:

* **Logs**: View live server logs.
* **Keys**:
    * `l`: Cycle log levels (DEBUG, INFO, ERROR).
    * `y`: Copy logs to clipboard.
    * `r`: Restart server.
    * `q` / `Ctrl+C`: Quit.

## `pywire run`

Starts the production server (Uvicorn wrapper). Optimizes for performance and concurrency.

```bash
pywire run [APP] [OPTIONS]
```

**Options:**

* `--host TEXT`: Bind host (default: `0.0.0.0`).
* `--port INTEGER`: Bind port (default: `8000`).
* `--workers INTEGER`: Number of worker processes (default: auto-calculated based on CPU cores).
* `--no-access-log`: Disable access logging for performance.

## `pywire build`

Compiles `.wire` files into optimized Python bytecode and generates build artifacts.

```bash
pywire build [APP] [OPTIONS]
```

**Options:**

* `--optimize`: Compile bytecode with optimization (python `-O`).
* `--out-dir TEXT`: Output directory (default: `.pywire/build`).
* `--pages-dir TEXT`: Override pages directory.

## `create-pywire-app`

(Separate command, typically run via `uvx`) Scaffolds a new project. See [Quickstart](/docs/guides/quickstart).
