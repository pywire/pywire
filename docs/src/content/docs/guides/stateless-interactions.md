---
title: Optimistic UI and fast lists
description: Make request-scoped interactions feel immediate without moving server logic into the browser.
---

## Optimistic UI

Add `.optimistic` to a DOM event to mark its target pending synchronously. Add one or more `.optimistic-class-<name>` modifiers to predict presentation classes:

```pywire
<button @click.optimistic.optimistic-class-bg-emerald-600={toggle_item(item.id)}>
    {item.name}
</button>
```

On dispatch, PyWire applies `data-pw-pending` and the declared classes before the next frame, and guards against a duplicate submit. The server remains the only source of business logic. The arriving morphdom patch is the reconciler: a correct prediction produces no visible change, while a rejected prediction is removed automatically. Inputs remain user-owned during the round-trip.

Do not use optimistic UI for:

- actions whose visual prediction cannot be expressed as a pending attribute/class;
- operations where duplicate prevention is a security boundary;
- per-token output or arbitrary progress that requires server push.

## Fast keyed lists

Give every loop a stable, unique key:

```pywire
<ul>
    <li $for={item in items, key=item.id}>
        {item.name}
        <button @click={toggle_item(item.id)}>{item.done}</button>
    </li>
</ul>
```

PyWire creates a keyed region for each iteration. Mutating one item re-renders and ships only that row. In the measured Cloudflare `workerd` gate, toggling one row in a 1000-row list produced a **251 B** update: O(n) list content collapsed to O(1) payload per item mutation.

Keys must be stable and unique. Duplicate or churning keys cannot safely identify DOM regions.

### v1 structural-change ceiling

Append, remove, reorder, or fully reassign the collection falls back to a whole-loop render. This is intentional v1 behavior, not a per-row incremental update. For interactions that repeatedly insert or reorder, expect the larger payload until structural keyed regions ship.

`key=` still improves identity tracking on stateful transports too; the same `render_update` shape is used by WebSocket, HTTP-session, and stateless transports.
