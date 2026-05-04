---
title: Error & Reconnect Pages
description: Customising the built-in error page and disconnect overlay.
---

PyWire ships with two built-in screens you can override by dropping convention
files into your `pages/` directory:

| File | Purpose |
| --- | --- |
| `pages/__error__.wire` | Renders 404s, uncaught exceptions, and SPA navigation errors. |
| `pages/__reconnect__.wire` | Overlay shown when the WebSocket drops, with a "failed" state once the client gives up. |

Both files start with `__` and are picked up automatically — they are not
routed and never collide with regular pages. Like `__layout__.wire`, they are
discovered explicitly by the page loader rather than scanned alongside other
pages. See [Layouts](/docs/guides/layouts) for the third convention file.

## `__error__.wire`

`pages/__error__.wire` replaces the default error template for both HTTP
errors (4xx/5xx) and uncaught exceptions raised inside a page.

The page receives two attributes from the framework:

| Attribute | Type | Description |
| --- | --- | --- |
| `error_code` | `int` | HTTP status code (e.g. `404`, `500`). |
| `error_message` | `str` | Human-readable summary. For 500s in production builds this is sanitised. |

```pywire
!no_spa

---
def headline():
    if error_code == 404:
        return "Page not found"
    if error_code == 500:
        return "Something went wrong"
    return "Error"
---

<main class="error">
    <p class="status">Error {error_code}</p>
    <h1>{headline()}</h1>
    <p>{error_message}</p>
    <a href="/">Back to home</a>
</main>

<style scoped>
    .error { max-width: 32rem; margin: 4rem auto; text-align: center; }
    .status { font-family: ui-monospace, monospace; opacity: 0.6; }
</style>
```

A few notes:

- **`!no_spa` is recommended.** Error pages are rendered as a different
  document than the page that triggered the error — leaving SPA enabled
  would morph the error template's `<head>` and styles into the live DOM.
- **Layouts apply.** If your root `pages/__layout__.wire` exists, the
  error page is wrapped in it automatically (matching how regular pages
  are wrapped). Pass `!no_layout` if you want a bare error page.
- **Compile errors during `pywire dev` use a different screen.** When a
  `.wire` file fails to compile in development, PyWire renders a
  dedicated syntax-error page from `templates/error/compile_error.html.j2`
  with the offending source line and traceback. This is dev-only and
  cannot be overridden — production builds never hit it.

## `__reconnect__.wire`

`pages/__reconnect__.wire` replaces the overlay shown when the client's
WebSocket drops. The file is loaded at startup as **static HTML and CSS** —
Python frontmatter and event handlers are ignored, since the browser is by
definition disconnected from the server when the overlay is visible.

The server injects your template as `<template id="_pywire_reconnect">` on
every page. When the transport disconnects, the client clones it into a
wrapper `<div id="_pywire_reconnect_overlay">` and toggles a single
attribute as state changes:

| `data-pw-reconnect-state` | When |
| --- | --- |
| `"reconnecting"` | Initial state. The transport is still attempting reconnects on its backoff schedule. |
| `"failed"` | The transport has exhausted `reconnect_max_attempts` (default `10`) and given up. |

Author both states inside the same template, then use CSS attribute
selectors on `#_pywire_reconnect_overlay` to swap between them.

```pywire
---
---
<div class="reconnect-card">
    <p class="msg-reconnecting">Hold tight, reconnecting&hellip;</p>
    <p class="msg-failed">Lost the wire. Try a reload.</p>
    <button class="reload-btn" type="button" onclick="location.reload()">Reload</button>
</div>

<style>
    /* Default state ("reconnecting"): hide the failed message + button. */
    #_pywire_reconnect_overlay .msg-failed,
    #_pywire_reconnect_overlay .reload-btn { display: none; }

    /* Failed state: swap which message is visible. */
    #_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .msg-reconnecting {
        display: none;
    }
    #_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .msg-failed,
    #_pywire_reconnect_overlay[data-pw-reconnect-state="failed"] .reload-btn {
        display: block;
    }

    /* Position over the page however you like — the overlay sits at the
       end of <body>, on top of your app's DOM. */
    .reconnect-card {
        position: fixed;
        inset: 0;
        display: grid;
        place-items: center;
        background: rgb(0 0 0 / 0.55);
        backdrop-filter: blur(3px);
        color: white;
        font-family: ui-sans-serif, system-ui, sans-serif;
    }
</style>
```

The empty `---` block is required so the file is parsed as a `.wire`
template; everything else is treated as static markup.

### Settings

The reconnect cap and overlay visibility are configurable on `PyWire(...)`:

```python
app = PyWire(
    pages_dir="pages",
    reconnect_max_attempts=10,   # how many times the client retries before giving up
    reconnect_overlay=True,      # set False to suppress the overlay entirely
)
```

When `reconnect_overlay=False`, the template is still injected but the
client never displays it — useful if you want a fully bespoke disconnection
indicator wired up from your own page code.

### What you cannot do

- **Run Python.** The file is static. Frontmatter logic, refs, and
  event handlers (`@click`, etc.) are stripped — the browser is
  disconnected from the server while the overlay is visible.
- **Reach the rest of your app's DOM.** Style selectors are scoped to
  `#_pywire_reconnect_overlay` to avoid leaking into the live page when
  the overlay is hidden. Selectors outside that wrapper still work but
  are not recommended.

For a fully styled reference, see the built-in default at
[`packages/pywire/src/pywire/templates/reconnect/default.html`](https://github.com/pywire/pywire/blob/main/packages/pywire/src/pywire/templates/reconnect/default.html).
