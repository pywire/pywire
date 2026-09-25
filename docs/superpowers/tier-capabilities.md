# PyWire tiers: stateless vs stateful — feature capability matrix

**Status:** observed reality as of `7bc1265` (2026-09-24), verified against tests and spike
probes — not aspiration. Every row cites evidence. `{$auth}` stateless support is landing as
Task 31 (owner mandate); its row reflects T31's behavior and is pinned by T31's tests.
Build enforcement of this matrix: §Build-time checks (Task 32, accepted at the T30 gate).

## The tiers

| Tier | Transport | Server state | Deploy targets |
|---|---|---|---|
| **Stateful** | WebSocket (interactive server mode) or HTTP-session | In-process page instances; push channel (`_on_update`) | Long-running servers: `pywire run`, Cloud Run, containers |
| **Stateless** | One-shot POST (`/_pywire/stateless`) + HMAC-signed snapshot round-trip | **None.** Every request rebuilds the page from the client-carried snapshot; identity always re-resolved from the request | Pure FaaS: Lambda, Azure Functions, GCP Functions, Cloudflare plain-Worker (`cloudflare-edge`) |

A third dimension, orthogonal to both: the **no-JS floor** (`!no_interactive` on a page) —
native form POSTs via a `__pywire_handler` hidden input, client JS loads but does not wire
events. Applies on either tier.

`PyWire(stateless=True)` is the **ceiling assertion**: "this deployment must run on pure FaaS —
no page may require server push." (Task 32 enforces it at build time.)

## Capability matrix

Legend: ✅ works · ⚠️ works with a stated floor · ❌ rejected or non-functional (and what to use instead)

### Template directives

| Feature | Stateful | Stateless | Behavior & evidence |
|---|---|---|---|
| `{expr}` interpolation | ✅ | ✅ | Render-time. |
| `{$if}` / `{:else if}` / `{:else}` | ✅ | ✅ | Render-time conditional. |
| `show=` | ✅ | ✅ | Class/attr toggle, render-time. |
| `{$for}` + `key=` | ✅ | ✅ | Keyed per-iteration regions (Phase 3): one row mutation ships one region, structural change falls back to full loop. Transport-agnostic — same `render_update` shape on WS, HTTP-session and stateless. Tests: keyed-region suite (T12), Spec #6 payloads. |
| `{$try}` / `{$except}` / `{$finally}` | ✅ | ✅ | Render-time error display. |
| `{$await}` + `then` / `catch` | ✅ | ❌ | Needs a push channel: holds the response open / pushes the resolved view. **Compile error on stateless** (Task 26 gate, `compiler/tier_gate.py`; `tests/test_tier_gating.py`). Use `@poll` + a task/store, or deploy stateful. |
| `{$auth}` region | ✅ | ✅ *(T31)* | Stateful: renders `pending`, pushes `allowed`/`denied` on resolution. Stateless **pre-T31: broken** — `push_state()` no-ops without `_on_update`, region stuck on PENDING forever (spike probe A-P6). T31: resolves inline in the same request; **verdicts are never snapshotted** — every request re-evaluates (revocation bites the next request). |
| `{$dynamic}` | ✅ | ✅ | Forces region dirty every update; render-time. |
| `snippet=` / `render=` | ✅ | ✅ | Template composition; render-time. |
| `{$head}` | ✅ | ✅ | Head management at render. |
| `...spread` attributes | ✅ | ✅ | Render-time. |

### Events & bindings

| Feature | Stateful | Stateless | Behavior & evidence |
|---|---|---|---|
| `@event={handler}` (any DOM event) | ✅ | ✅ | Identical dispatch path on both tiers — the client sends through `app.sendEvent` → transport; zero tier-specific branching (`client/src/events/handler.ts`; transport parity pinned in Phase 2 + `tests/e2e/`). |
| `.prevent` / `.stop` modifiers | ✅ | ✅ | Client-side. |
| Handler args: `@click={f(x)}` | ✅ | ✅ | Args lifted to `data-arg-*`, browser enumerates `arg-0`, server normalizes to `arg0` (`page.py` `_dispatch_handler`). Chain pinned: codegen test, `test_rendering.py:136`, `test_poll_arg_reaches_handler`, `client/src/events/poll.test.ts`. |
| `@poll={handler}` + `.every-<ms>` | ✅ | ✅ | **Kernel — identical on both tiers** (Task 28/29). Interval dispatch through the same event path; stop = conditional render (element unmounts; no `.while` in v1 — documented ceiling). Overlap guard is best-effort (global reset on any response). e2e both transports: `tests/e2e/test_poll.py`. |
| `bind:` two-way + bind echo | ✅ | ✅ | Inputs stay user-owned during round-trip (Task 16). |
| `.optimistic-class-<name>` | ✅ | ✅ | Optimistic prediction + pending guard + morph reconcile; a prediction never survives server contradiction (Tasks 14–17, Spec #8). |

### State, lifecycle & auth

| Feature | Stateful | Stateless | Behavior & evidence |
|---|---|---|---|
| Frontmatter wires (page state) | ✅ | ✅ | Stateful: server-held. Stateless: serialized into an HMAC-signed msgpack snapshot per request (`runtime/snapshot_codec.py`; stdlib hmac/hashlib/base64 only). Tamper/replay-with-wrong-secret → 400, no mutation (Spec #1). |
| `.lock()` wires | ✅ | ✅ | Client-invisible on both tiers — never emitted in a snapshot, re-initialized by frontmatter on restore (Spec #2). |
| `@init` hook | ✅ | ✅ | Runs before first render (`render(init=True)`). Stateless event round-trips use `render(init=False)` — hooks do not re-run; a fresh page load re-runs them (no server memory to memoize across requests). |
| `@before_load` hook | ✅ | ✅ | Same semantics as `@init`. |
| `push_state()` | ✅ | ❌ | Streams an update to the open client. Stateless is one-shot — `push_state` no-ops (no `_on_update`; `page.py`). For progress UI on stateless: `@poll`. For per-token streaming: stateful tier (SSE is roadmap). |
| `!auth` page guard | ✅ | ✅ | Anonymous request → redirect-to-login on all three transports (303 / WS `navigate` / stateless `navigate`; spike A-P8). Since `7bc1265`, the guard runs **before** handler dispatch on every path (forged handler names cannot execute side effects first). |
| `page.user` identity | ✅ | ✅ | Always resolved from the request (session/middleware), never from the client snapshot — popped at encode and again at restore (defense in depth, `snapshot_codec.py` + `stateless_handler.py`). A stolen snapshot is not a stolen session. |
| Sessions & cookies | ✅ | ✅ | Session middleware sits inside the Starlette app on both tiers — full middleware parity by construction (stateless endpoint mounted inside the app) and verified (spike A-P8). |
| `navigate()` | ✅ | ✅ | SPA-nav message on WS/stateless; normal navigation on no-JS. |
| Components + `on_*` callback props | ✅ | ✅ | Plain props; unwired values passed to handlers (post-`unwrap_wire`, pinned by regression test). |

### Server push & multi-user

| Feature | Stateful | Stateless | Behavior & evidence |
|---|---|---|---|
| Background completion → UI update (`{$await}`) | ✅ | ❌ | See `{$await}` row. |
| Per-token chat/streaming UX | ✅ | ❌ | Bounded waits on stateless → `@poll`; per-token → stateful; SSE is roadmap (docs guidance). |
| Rooms / shared push channels | ❌ | ❌ | **Not implemented on either tier** (accepted loss). Multi-user read patterns work statelessly via a shared store + `@poll`. |

### Infrastructure & edge cases

| Feature | Stateful | Stateless | Behavior & evidence |
|---|---|---|---|
| SPA navigation / pjax | ✅ | ✅ | Stateless falls back to a full page load for snapshot-less navigations (`client/src/core/transports/stateless.ts`); cross-tier navigation = full load (`data-pw-reload` per-link escape hatch). |
| File uploads | ✅ | ✅ | Task 27. Token injection fails closed (no token → 403); token charset validated (`7bc1265`). |
| No-JS form floor (`!no_interactive`) | ✅ | ⚠️ | Works on both tiers (`__pywire_handler`, Task 27; guard + underscore refusal hardened in `7bc1265`). **Floor:** a stateless no-JS POST carries no snapshot → page state resets (safe: handler runs, re-renders, no crash). Deferred: `__pywire_snapshot` hidden input. |
| Error pages | ✅ | ✅ | `PyWire(debug=True)` UX identical (error pages, stack traces, source endpoints). |
| Debug snapshot inspector (`/_pywire/debug/snapshot`) | n/a | ✅ (dev-only) | Stateless-only by nature (stateful has no snapshot secret); 404 elsewhere (`_is_dev_mode` + `debug` gate, `7bc1265`). |
| Keyed-region payload diffs | ✅ | ✅ | Same `render_update` output shape on every transport — the payload win applies everywhere. |
| Dev hot reload | ✅ | ✅ | Dev compiles from source, so tier gating fires in dev renders as well as `pywire build`. Precompiled artifacts are gated at build time (the gate runs in the build pipeline). |

## Build-time checks

The matrix above is enforced where it can be statically proven, in **one code location**
(`packages/pywire/src/pywire/compiler/tier_gate.py`, extended by Task 32) consumed by both
dev-compile and `pywire build`.

### The feature → minimum-tier map (the enforcement core)

| Page feature (in the page's transitive component closure) | Minimum tier | Check result on a `stateless=True` build |
|---|---|---|
| `{$await}` blocks | push | ❌ build error: name page + feature + suggest `@poll`/stateful |
| `push_state()` in handler bodies | push | ❌ build error (when statically visible) |
| `{$auth}` region | plain (post-T31) | ✅ builds — resolves inline statelessly |
| `@poll`, `@event`, forms, uploads, `bind:`, `.optimistic`, keyed `{$for}`, all render-time directives | plain | ✅ builds |
| nothing | plain | ✅ builds |

### How it works (today → Task 32)

- **Today (Task 26):** a recursive AST walk rejects `{$await}` per file at compile time —
  dev render and `pywire build` both fail with an actionable error (names the page, points at
  `@poll`/stateful). `tests/test_tier_gating.py`, including the nested `{$for}`→`{$await}` case.
- **Task 32 (accepted 2026-09-24):** the walk generalizes into the map above and runs
  **per page over its transitive component closure** — a shared component with `{$await}`
  fails only the pages that actually use it, and the error names that page. `PyWire(stateless=True)`
  becomes the ceiling assertion ("fail the build if any page needs push"). The per-file walk
  is replaced, not layered.

### What the check cannot see (stated, not pretended)

Static analysis is syntactic. Per the T30 spike (probes C2/C3):

- A push triggered inside an **imported helper** is invisible to the page's scan.
- **Dynamic dispatch** (`getattr`, computed handler names) defeats any allowlist/scan.
- `create_task()` alone is **not** a tier signal — the flagship stateless pattern
  (`@poll` + background task) uses it. Tier-needing is about *push*, not *background work*.

The gate is therefore a strong default with documented edges — it catches direct feature use
(the overwhelming majority), and the docs say what remains the app author's responsibility.

## Known floors & deferred decisions (accurate as of this commit)

| Item | State | Impact |
|---|---|---|
| Stateless no-JS form POST resets page state | deferred (`__pywire_snapshot` hidden input if continuity wanted) | Safe: handler runs, page re-renders |
| Snapshot replayability + `path` not signed into the blob | deferred (design decision) | Moderate-low: a stolen blob replays page state but carries no identity; revocation/re-binding is a product choice |
| Rate limiting on `/_pywire/stateless` (poll cadence floor is client-side) | deferred (framework policy; T25 docs) | Standard reverse-proxy/FaaS throttling is the mitigation |
| Poll overlap guard best-effort (global reset on any response) | accepted v1 (strict per-element needs WS request-id correlation) | Click path has no guard at all — poll is above the bar |
| Multiple `@poll` attributes on one element silently dropped | → Task 24 parser floor | Low |
| `getArgs` duplicated (`poll.ts` / `handler.ts`) | deferred cleanup | Drift risk only |
| WS reconnect does not reset poll `inFlight` | deferred one-liner | Self-heals on next response |
