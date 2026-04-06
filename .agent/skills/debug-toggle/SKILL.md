---
name: debug-toggle
description: Toggle PyWire debug logging (server and client).
---

# PyWire Debug Toggle Skill

This skill allows you to easily enable or disable debug logging for both the PyWire server and client.

## Usage

### Enable Debug Mode
To enable debug mode, set the `PYWIRE_DEBUG` environment variable to `1` when starting the server.

```bash
PYWIRE_DEBUG=1 uv run pywire dev src.main:app
```

### Disable Debug Mode
To disable debug mode, either unset `PYWIRE_DEBUG` or set it to `0`.

```bash
PYWIRE_DEBUG=0 uv run pywire dev src.main:app
```

## How it Works
- **Server-Side**: The `PyWire` app constructor checks the `PYWIRE_DEBUG` environment variable. If set to `1`, `true`, or `yes`, `self.debug` is set to `True`. `BasePage` then uses this flag to gate `DEBUG` print statements.
- **Client-Side**: The server injects the `debug` flag into the SPA metadata. The client-side `Logger` class respects this flag, hiding `console.log` and `console.warn` statements when debug mode is off.
