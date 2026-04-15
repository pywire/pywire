---
name: debug-toggle
description: Toggle PyWire debug logging (server and client).
---

# PyWire Debug Toggle Skill

This skill allows you to easily enable or disable debug logging for both the PyWire server and client.

## Usage

### Enable Internal Framework Logging
To enable internal framework debug logging (wire tracking, render regions, page init), set `PYWIRE_LOG_LEVEL`:

```bash
PYWIRE_LOG_LEVEL=DEBUG uv run pywire dev src.main:app
```

### App-Developer Debug Mode
The `debug=True` constructor flag controls app-developer UX: error screens, stack traces, source endpoints. It does NOT control internal framework logging.

```python
app = PyWire(debug=True)
```

## How it Works
- **Server-Side**: `PYWIRE_LOG_LEVEL` env var controls the `pywire` logger level (default: WARNING). This is separate from `debug=True` which controls app-developer features like error detail pages and source code endpoints.
- **Client-Side**: The server injects the `debug` flag into the SPA metadata. The client-side `Logger` class respects this flag, hiding `console.log` and `console.warn` statements when debug mode is off.
