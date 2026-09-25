---
title: Stateless mode
description: Use signed page snapshots, locked wires, and small request-scoped state on FaaS and edge runtimes.
---

Stateless mode replaces server-held page sessions with a signed client-carried snapshot. The server performs one round-trip per event:

1. The browser sends the snapshot, allowlisted handler name, event data, and current path to `POST /_pywire/stateless`.
2. PyWire verifies the HMAC-SHA256 signature, reconstructs the page, and resolves identity from the current request.
3. The handler runs and receives **unwrapped values, not live Wire objects**.
4. PyWire renders dirty regions, signs the next snapshot, and returns both.

`page.user` is never included in a snapshot. Authentication, middleware, and session cookies run on the same POST as a normal HTTP load.

## Security notes

- Invalid signatures, corrupt data, and non-snapshot payloads fail with HTTP 400 before state mutation.
- Handler dispatch uses a compile-time allowlist.
- Keep a single strong `PYWIRE_SECRET_KEY` across every instance serving that app. Never auto-generate or commit it.
- Snapshot integrity is not authorization. A bearer of a valid snapshot can replay its non-identity page state; authorization must still be enforced in handlers and request-derived identity.
- The snapshot's `path` field is unsigned: a valid snapshot can be transplanted to another route (cross-page). Impact is bounded — identity is stripped and re-resolved per request, and page guards re-run on every request. (Known accepted gap.)

`{$auth}` works in stateless mode, but **verdicts are never snapshotted**. Each request re-evaluates the policy, so revocation takes effect on the next request.

## Keep snapshots small: the O(n) design pattern

Snapshot size grows with the number of public wires and their values. Do not copy a large result set into page state for every request. Use a locked wire as a request-local handle and fetch the current data from the store:

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

## The no-JS floor

With `!no_interactive`, a form POST still runs its declared handler without JavaScript. In stateless mode, that form does **not** carry the interactive snapshot, so non-persisted page state resets for that request. The handler still runs and the response still renders. Persist continuity in the form's target store when the no-JS path must retain it.

## Build-time enforcement

`pywire build` enforces the stateless ceiling over each page and its statically resolvable component closure. `{$await}` and directly visible `push_state()` calls are errors. The scan cannot see push hidden behind imported helpers, dynamic dispatch, or unresolved dynamic component paths. Review those edges yourself. `create_task()` alone is not a tier signal: background work without server push is valid on stateless.
