# pywire-cli

Command-line tools for [PyWire](https://pywire.dev) projects: `dev`, `run`, `build`, `deploy`, `check`.

Normally installed via the `pywire[cli]` extra:

```sh
uv add pywire[cli]
# or
pip install pywire[cli]
```

This installs `pywire-cli` alongside the core framework and makes the `pywire` command available.

## Commands

- `pywire dev` — run the development server with hot reload
- `pywire run` — run the production server
- `pywire build` — compile the project for production
- `pywire deploy` — generate deployment configs (Docker, Render, Fly, Railway, Cloudflare)
- `pywire check` — run static analysis on the project (non-serializable wires, reactivity errors, redundant patterns)
- `pywire config` — read/write PyWire settings
