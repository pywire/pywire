# Edge Stateless Mode — guided demo

A minimal PyWire app that showcases the four "edge stateless" features:

1. **Stateless mode** — page state travels with the client, no WebSocket, no
   server-side session. Runs on a plain request/response (FaaS/edge) worker.
2. **Keyed `{$for}` regions** — a 300-row list where toggling one row ships
   only that row's HTML.
3. **Optimistic UI** — instant click feedback with automatic reconciliation,
   including auto-revert of wrong predictions.
4. **Stateless `{$await}`** — how budget-bounded awaits behave without
   server memory (and where they stop working): `/await` in the demo.

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

Why *prediction*: the client does not know the server's decision. The
modifier declares a guess — "render this as if the server already said
yes" — and the arriving patch is the referee. Right guess: the patch is a
visible no-op. Wrong guess: the patch silently strips the class.

### Await in stateless mode

In the stateful (Durable-Object/WebSocket) tier, `{$await}` runs on the
server for as long as it takes and pushes the result when it is ready. In
stateless mode there is no long-lived server: the await runs *inside the
request*. `PyWire(await_budget=N)` bounds how long — at the deadline,
still-pending tasks are **cancelled** (their results are lost: no
background job, no retry, nothing to push through) and the response ships
the block's fallback text plus a count in `meta.pending_awaits`.

Observed contract (all measured on this demo):

- **Initial page loads don't run awaits at all** — the GET ships the
  fallback texts instantly; await content only appears on event
  re-renders.
- **Event POSTs hold open up to the budget** — the 1 s dependency answers
  inside it, the 10 s one never does, and an unknown one is a coin flip
  per render.
- **Every re-render re-runs its await blocks** — a slow dependency taxes
  every interaction with the page, not just the load.

Rules of thumb: keep `await_budget` below your platform's hard request
timeout (Workers, Lambda and every API gateway has one), remember you pay
FaaS wall-clock for held-open requests, and treat dependencies you cannot
bound as stateful-tier features.

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

4. **Wrong prediction — auto-revert.** Click **Like** once and *wait* for
   it. The handler sleeps 500 ms, and the server refuses every *second*
   like. On each click the red `liked` class pops on instantly — that is
   the prediction: the client has no idea yet whether the server will
   accept this like, it just renders your declared guess immediately and
   lets the server's patch be the referee. On an accepted click the class
   simply stays (right guess — the patch is a visible no-op). On a refused
   click, watch the red hold for the round-trip and then snap back when the
   patch lands without it — auto-revert, with no error handling anywhere
   (see `like()` in `src/pages/index.wire`).

5. **SPA navigation — state resets, but it is NOT a page reload.** Click
   **About** in the nav, then **Back home**. Every page carries its own
   snapshot, so the state you built up is **reset** on return — the v1
   ceiling below, visible on purpose. A reset alone is indistinguishable
   from a full reload, so here's how to *see* the difference:
   - **Console marker (the definitive proof).** Before navigating, run
     `window.__pwcheck = 1` in the console. Click About, then Back home — it's
     still `1`. A real browser reload would have wiped it: the JS context
     survives because the client only morphs the DOM.
   - **Network.** The hop shows as a **fetch** of `/about` (Fetch/XHR filter),
     *not* a document navigation — and note there is **no**
     `/_pywire/stateless` POST: the fresh state rides *inside* the fetched
     page's HTML, as an embedded snapshot.
   - **Chrome UI.** The URL changes via `history.pushState`; the reload
     button never spins, no white-flash navigation.

   The browser's Back button behaves the same (popstate is wired). The point:
   the only memory in stateless mode is the signed snapshot inside the page
   you're looking at — returning re-GETs the page, which re-mints it from
   initial frontmatter state. In the Durable-Object/WebSocket tier the
   server-side session would still remember your counter.

6. **Stateless `{$await}` — bounded by budget, not by patience.** Open
   **Await** in the nav. This app sets `PyWire(await_budget=2.0)` and the
   page simulates three dependencies you don't control: 1 s (inside
   budget), 10 s (beyond it), and 0.5–6 s (unknown). What you'll observe:
   - The page loads instantly with all three *fallback* texts — the
     initial GET does not run awaits; their content only appears on event
     re-renders.
   - Click **Re-roll**. The POST takes ≈ 2 s — exactly the budget. When it
     lands: the 1 s block morphs to its answer, the random block is a
     coin flip, and the 10 s block **never** answers — its task was
     cancelled at the budget and the fallback you see is permanent for
     that render. The result is lost; nothing finishes it later.
   - Click Re-roll again and note the POST cost: every re-render re-runs
     the awaits, so a slow dependency taxes *every* interaction.
   - The count of abandoned await work rides in the response's msgpack
     `meta.pending_awaits` (Network → the POST response body — binary
     msgpack, a viewer extension helps). The client renders nothing from
     it; it is telemetry for your code.

## v1 ceilings

- **State resets on SPA nav.** Snapshots are per-page; navigating away and
  back re-renders the page from its initial state.
- **Structural list changes re-ship the whole loop.** Append/remove/reorder
  dirty the loop region as a whole; the per-row patching is for *in-place*
  item mutations (like the toggle here).
- **No server push.** Stateless mode mounts no WebSocket — updates only
  happen in response to client events.
- **Awaits are request-bounded.** `{$await}` content only arrives inside
  a response that waited for it (≤ `await_budget`); anything slower is
  cancelled and lost, and initial loads don't run awaits at all. No
  background completion, no push — see `/await` in the demo.
- **Snapshot size scales with page state.** Every POST carries the full
  snapshot and every response returns a fresh one. This demo's 300-row list
  makes the snapshot ~11.4 KB, so each event is an ~11.5 KB msgpack POST
  (the event envelope itself is under 100 B; a counter-only page posts just
  275 B — measured — which is where the "~300 B per event" headline comes
  from). What stays tiny is the *patch* — 326 B for one row.
