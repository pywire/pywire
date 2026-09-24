# Edge Stateless Mode — guided demo

A minimal PyWire app that showcases the three "edge stateless" features:

1. **Stateless mode** — page state travels with the client, no WebSocket, no
   server-side session. Runs on a plain request/response (FaaS/edge) worker.
2. **Keyed `{$for}` regions** — a 300-row list where toggling one row ships
   only that row's HTML.
3. **Optimistic UI** — instant click feedback with automatic reconciliation,
   including auto-revert of wrong predictions.

## Run it

```sh
cd examples/demo-edge-stateless
uv sync
uv run pywire dev
```

Open the printed URL (typically <https://localhost:3000> — the dev server
auto-generates a local mkcert certificate, so it's HTTPS).

The page state is HMAC-signed with `PYWIRE_SECRET_KEY` if set; otherwise
`src/main.py` falls back to a clearly-marked dev-only key. Set the env var
for anything beyond local poking:

```sh
PYWIRE_SECRET_KEY=$(openssl rand -hex 32) uv run pywire dev
```

## What changed

### Stateless transport

`PyWire(stateless=True, secret_key=...)` moves page state to the client. Each
render embeds an HMAC-signed snapshot of the page's wires in the HTML
(`<script id="_pywire_snapshot">`), and every event is one self-contained
`POST /_pywire/stateless` (msgpack) that carries the snapshot in and returns
a fresh snapshot plus a minimal HTML patch. The server verifies the
signature, runs the handler, and forgets everything — no WebSocket, no
sticky sessions, any edge worker can serve it (see
`pywire.adapters.oneshot.OneShotASGIAdapter`).

### Keyed regions

`{$for item in items.value, key=item["id"]}` wraps each iteration in its own
sub-region (`data-pw-region="<site>#<key>"`). When a handler mutates one
item, only that item's region is dirtied — the patch is just that row's
wrapper HTML (a few hundred bytes) no matter how long the list is. Without
`key=`, any mutation re-renders and re-ships the whole loop. `key=` takes any
expression: `key=item.id` for attribute-style objects, `key=idx`, etc.

### Optimistic UI

`@click={handler}` accepts presentation-only prediction modifiers:
`.optimistic` (predict "in flight") and `.optimistic-class-<name>` (predict a
CSS class). On click the client synchronously adds the class(es), stamps
`data-pw-pending`, and blocks double-submit until the response's patch
reconciles the element. The server render is always the truth: if a
prediction doesn't match what the server says, the class auto-reverts — no
error handling anywhere.

## Try it

Open DevTools (Network + Elements side by side) and walk down the page.

1. **Optimistic counter.** Click **Increment**. In Elements the button gets
   `class="btn dim"` and `data-pw-pending` *synchronously on click*, before
   any network activity. Network shows exactly one `POST /_pywire/stateless`
   per click — msgpack request/response, **no WebSocket frames anywhere**
   (the WS tab stays empty; stateless mode mounts no WS route at all).
   When the response lands, `dim` and `data-pw-pending` are stripped and the
   count updates.

2. **Slow action + double-submit guard.** Click **Slow increment**. The
   predicted `dim` class stays visible for ~500 ms (the handler sleeps
   `await asyncio.sleep(0.5)`) — the prediction window is plainly visible in
   Elements. Now spam-click it: **exactly one Network entry appears**. While
   `data-pw-pending` is present the button is disabled and re-clicks are
   dropped — one POST total, no matter how fast you click.

3. **Keyed list — tiny patches.** Scroll to the 300-row list, pick a row in
   the middle (say `item-150`) and click **toggle**. The button flips to its
   green `done` class instantly (predicted), and the row reconciles when the
   patch lands. In Network the response size stays tiny — the patch carries
   exactly ONE region: that row's `<li>` wrapper HTML (measured: **326 B**
   for one row). In Elements only that row's `data-pw-region="<site>#150"`
   node is morphed; its 299 siblings are untouched.

4. **Wrong prediction — auto-revert.** Click **Like**. The red `liked` class
   pops on instantly, but this server refuses every second like. On a
   refused click, watch the class appear and then vanish when the server's
   patch lands — the prediction was reverted automatically because the
   server render disagrees. No error handling in app code (see `like()` in
   `src/pages/index.wire`).

5. **SPA navigation.** Click **About** in the nav, then **Back home**.
   Navigation is client-side (no full reload) but every page carries its own
   snapshot — so the counter/list state you built up is **reset** when you
   return. That's the v1 ceiling below, and it's visible here on purpose.

## v1 ceilings

- **State resets on SPA nav.** Snapshots are per-page; navigating away and
  back re-renders the page from its initial state.
- **Structural list changes re-ship the whole loop.** Append/remove/reorder
  dirty the loop region as a whole; the per-row patching is for *in-place*
  item mutations (like the toggle here).
- **No server push.** Stateless mode mounts no WebSocket — updates only
  happen in response to client events.
- **Snapshot size scales with page state.** Every POST carries the full
  snapshot and every response returns a fresh one. This demo's 300-row list
  makes the snapshot ~11.4 KB, so each event is an ~11.5 KB msgpack POST
  (the event envelope itself is under 100 B; a counter-only page posts just
  275 B — measured — which is where the "~300 B per event" headline comes
  from). What stays tiny is the *patch* — 326 B for one row.
