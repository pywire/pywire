---
title: CLI Reference
description: Comprehensive guide to the pywire command-line interface.
---

The `pywire` CLI is your primary tool for developing, building, and serving applications. It ships as a separate [`pywire-cli`](https://pypi.org/project/pywire-cli) package; installing `pywire[cli]` pulls it in transparently.

## Global Flags

- `--help`: Show help message and exit.
- `--version`: Show the version number.

## `pywire dev`

Starts the development server.

```sh
pywire dev [APP] [OPTIONS]
```

- **APP**: The application string (e.g., `main:app`). Optional if `main.py` or `app.py` exists.

**Options:**

- `--host TEXT`: Bind host (default: `127.0.0.1`).
- `--port INTEGER`: Bind port (default: `3000`).
- `--ssl-keyfile TEXT`: Path to SSL key file.
- `--ssl-certfile TEXT`: Path to SSL certificate file.
- `--env-file TEXT`: Path to .env file.
- `--no-tui`: Disable the Terminal User Interface and output standard logs.

### The TUI Dashboard

Running `dev` opens a rich dashboard:

- **Logs**: View live server logs.
- **Keys**:
  - `l`: Cycle log levels (DEBUG, INFO, ERROR).
  - `y`: Copy logs to clipboard.
  - `r`: Restart server.
  - `q` / `Ctrl+C`: Quit.

## `pywire run`

Starts the production server (Uvicorn wrapper). Optimizes for performance and concurrency.

```sh
pywire run [APP] [OPTIONS]
```

**Options:**

- `--host TEXT`: Bind host (default: `0.0.0.0`).
- `--port INTEGER`: Bind port (default: `8000`).
- `--workers INTEGER`: Number of worker processes (default: auto-calculated based on CPU cores).
- `--no-access-log`: Disable access logging for performance.

## `pywire build`

Compiles `.wire` files into optimized Python bytecode and generates build artifacts.

```sh
pywire build [APP] [OPTIONS]
```

**Options:**

- `--optimize`: Compile bytecode with optimization (python `-O`).
- `--out-dir TEXT`: Output directory (default: `.pywire/build`).
- `--pages-dir TEXT`: Override pages directory.

## `pywire check`

Runs static analysis on your project's `.wire` files. Flags non-serializable `wire()` initial values, writes to wires inside a `derived()` body, redundant `{x.value}` interpolation, and more as the rule set grows.

```sh
pywire check [APP] [OPTIONS]
```

**Options:**

- `--pages-dir TEXT`: Override pages directory.
- `--rule CODE`: Only run specific rules (e.g. `--rule PW001 --rule PW003`). Repeatable. Default: all rules.
- `--plain`: Emit ruff-style plain text (`file:line:col: severity [code] message`) for CI / greppable logs.
- `--strict`: Exit 1 on any warning or info. Default exits 1 only on errors.
- `--fix`: Stub — not implemented yet.

`pywire build` runs the same analysis automatically and blocks on any `error`-severity diagnostic.

**Rule codes:**

- `PW001` — `wire()` assigned a non-serializable initial value
- `PW002` — wire write inside a `derived()` body (raises `ReactivityError`)
- `PW003` — redundant `.value` in template interpolation
- `PW004`–`PW010` — stubbed for upcoming releases

## `pywire deploy`

Generates deployment configuration files for your app.

```sh
pywire deploy [APP] [OPTIONS]
```

The command builds your project, validates the setup, and generates platform-specific config files (Dockerfile, render.yaml, etc.).

**Options:**

- `--platform {docker,render,fly}`: Target platform (default: `docker`).
- `--out-dir PATH`: Output directory for generated files (default: `.`).

**Examples:**

```sh
# Generate a Dockerfile
pywire deploy --platform docker

# Generate a render.yaml for Render.com
pywire deploy --platform render

# Generate into a subdirectory
pywire deploy --platform docker --out-dir deploy/
```

See [Deployment](/docs/guides/deployment) for platform-specific guides.

## `create-pywire-app`

(Separate command, typically run via `uvx`) Scaffolds a new project. See [Quickstart](/docs/guides/quickstart).
