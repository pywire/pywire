---
title: Stateless mode
description: Use signed page snapshots, locked wires, and small request-scoped state on FaaS and edge runtimes.
---

Stateless mode replaces server-held page sessions with a signed client-carried snapshot. The server performs one round-trip per event:

1. The browser sends the snapshot, allowlisted handler name, event data, and current path to `POST /_pywire/stateless`.
2. PyWire verifies the HMAC-SHA256 signature, inflates the zlib-compressed msgpack body, reconstructs the page, and resolves identity from the current request.
3. The handler runs and receives **unwrapped values, not live Wire objects**.
4. PyWire renders dirty regions, signs the next snapshot, and returns both.

`page.user` is never included in a snapshot. Authentication, middleware, and session cookies run on the same POST as a normal HTTP load.

## Security notes

- Invalid signatures, corrupt data, and non-snapshot payloads fail with HTTP 400 before state mutation.
- When the server rejects the page's snapshot (for example after a deploy or a key rotation) or it is over the size limit, the browser reloads the page, which embeds a fresh snapshot.
- Handler dispatch uses a compile-time allowlist: the functions a template wires by name (`@click={save}`) plus the wrappers generated for expressions (`@click={charge(price)}`). A function reached only through an expression can't be called directly with arguments the client chose.
- The endpoint only accepts `Content-Type: application/x-msgpack` from the same origin. Content types an HTML form can send are refused with HTTP 415, and requests the browser marks as cross-site with HTTP 403, so another site can't make a visitor's browser post a snapshot with their cookies.
- Keep a single strong `PYWIRE_SECRET_KEY` across every instance serving that app. It must be at least 32 bytes; generate one with `python -c 'import secrets; print(secrets.token_hex(32))'`. Never auto-generate or commit it.
- Snapshot integrity is not authorization. A bearer of a valid snapshot can replay its non-identity page state; authorization must still be enforced in handlers and request-derived identity.
- Each snapshot is bound to the URL (path and query) it was rendered for. Posting it with any other path is rejected with HTTP 400.
- `@before_load` and `@init` run on the page load that issues the snapshot, not on events. A check that must hold on every event belongs in the handler, or in `{$auth}` and `!auth`, which re-run on every request.
- The snapshot is signed, not encrypted. Anyone who can load the page can decode every public page attribute, including plain frontmatter values like `api_key = os.environ["API_KEY"]`. Keep secrets and server-only data in locked wires: `api_key = wire(os.environ["API_KEY"]).lock()`.

`{$auth}` works in stateless mode, but **verdicts are never snapshotted**. Each request re-evaluates the policy, so revocation takes effect on the next request.

## Keep snapshots small: the O(n) design pattern

Snapshot size grows with the number of public wires and their values. Do not copy a large result set into page state for every request.

:::caution[Every event pays for the whole page]
The snapshot travels in both directions on every event, and the server rebuilds the page with a full render before running the handler, so per-event cost grows with page state even when the update is one row. Measured on one server core with a 1,000-row keyed list held in a public wire: the snapshot is 3.3 KB (zlib-compressed from 28 KB) and each toggle takes about 20 ms, against about 0.5 ms for a counter. At 5,000 rows it is about 100 ms. Keep bulk data in locked wires, as below.
:::

Use a locked wire as a request-local handle and fetch the current data from the store:

```pywire
---
page_size = wire(50).lock()
page_number = wire(0)
rows = wire([]).lock()
user_id = wire(None)  # replaced from resolved request identity

def load_rows():
    rows.value = db.list_rows(user_id=user_id.value,
                              limit=page_size.value,
                              offset=page_number.value * page_size.value)

load_rows()
---
```

Locked wires such as `page_size` and `rows` are skipped by the snapshot encoder. Frontmatter recreates them and rebuilds the current request's bulk data and credentials from the store, so neither is carried O(n) in every round-trip. Put only small interaction state—filters, selection, pagination—in public wires. The list itself is an O(1) region update, but the snapshot is only small if you do not duplicate the collection there.

The value of `.lock()` is that it is client-invisible, not encrypted. Locked values can still exist in process memory during the request; do not put a value there that the frontmatter cannot reconstruct safely.

## Shared state

A module-level wire, a `producer()`, or a `derived()` that reads either is shared state: it can change without this page doing anything. A stateful app pushes those changes to every open page. A stateless app has no connection to push on, so the browser re-reads shared state on an interval instead.

Set the interval for the whole app, in seconds:

```python
app = PyWire(stateless=True, live_every=5)
```

Override it on a page:

```pywire
!live 1s
```

`!live 500ms` also works, and `!live off` turns refreshing off for that page. `live_every=0` turns it off for the app.

- Only pages whose render read shared state refresh. A page that shows only its own wires never polls.
- Every stateless request, whether an event or a refresh, re-renders the regions that read shared state and sends only the ones that changed since the browser last saw them.
- Refreshes pause while the tab is hidden and run as soon as it is visible again.
- Stateful apps ignore `live_every` and `!live`.

If a stateless page reads shared state and neither `live_every` nor `!live` is set, `pywire dev` shows an error naming the page and the value. Outside dev, PyWire logs a warning once and the page doesn't refresh on its own.

:::caution[Module state is per instance]
Each server instance, and each FaaS isolate, has its own copy of a module-level wire. It resets on a cold start and differs between instances, so a refresh shows whatever the instance that answered holds. PyWire logs a warning the first time a stateless event writes one. Keep state that users share in a database or key-value store, and read it through a producer, which counts as shared state and runs again on every request:

```pywire
---
import db
from pywire import producer

latest = producer([], lambda set_value: set_value(db.latest_messages()))
---
<ul><li $for={m in latest.value}>{m}</li></ul>
```

:::

A module-level wire assigned to a page attribute (`votes = shared.votes`) stays shared. It is not written into the snapshot, and a snapshot never overwrites it.

## The no-JS floor

With `!no_interactive`, a form POST still runs its declared handler without JavaScript. In stateless mode, that form does **not** carry the interactive snapshot, so non-persisted page state resets for that request. The handler still runs and the response still renders. Persist continuity in the form's target store when the no-JS path must retain it.

## Build-time enforcement

`pywire build` enforces the stateless ceiling over each page and its statically resolvable component closure. `{$await}` and directly visible `push_state()` calls are errors. The scan cannot see push hidden behind imported helpers, dynamic dispatch, or unresolved dynamic component paths. Review those edges yourself. `create_task()` alone is not a tier signal: background work without server push is valid on stateless.
