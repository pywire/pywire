---
title: Tier feature matrix
description: What works in stateless, stateful, and no-JavaScript PyWire deployments.
---

PyWire features fall into a kernel shared by both tiers, features that require a server-owned timeline, and a no-JavaScript floor. "Works statelessly" means the request can complete without holding a page instance or sending a server push.

| Feature                                                                             | Stateless     | Stateful    | No-JS floor / note                                                                              |
| ----------------------------------------------------------------------------------- | ------------- | ----------- | ----------------------------------------------------------------------------------------------- |
| Interpolation, `{$if}`, `$show`, `{$try}`, `{$dynamic}`, snippets, layouts, spreads | Yes           | Yes         | Render-time                                                                                     |
| DOM events, inline handler args, `.prevent`, `.stop`                                | Yes           | Yes         | `@submit` works through a native POST                                                           |
| `@poll` and `.every-<ms>`                                                           | Yes           | Yes         | No polling without JS; use a submit/refresh flow                                                |
| `bind:` and optimistic modifiers                                                    | Yes           | Yes         | JavaScript interaction only                                                                     |
| Keyed `{$for ... key=...}`                                                          | Yes           | Yes         | Structural changes fall back to the whole loop in v1                                            |
| Forms, validation, uploads                                                          | Yes           | Yes         | Form POST runs; stateless no-JS POST has no interactive snapshot, so non-persisted state resets |
| Frontmatter wires and components                                                    | Yes           | Yes         | State differs by tier                                                                           |
| `wire.lock()`                                                                       | Yes           | Yes         | Client-invisible and reconstructed from frontmatter                                             |
| `page.user`, auth guards, middleware, `{$auth}`                                     | Yes           | Yes         | Identity is always resolved from the current request; auth verdicts are never snapshotted       |
| File uploads and SPA navigation                                                     | Yes           | Yes         | Stateless falls back to full load when no snapshot exists                                       |
| Debug snapshot inspector                                                            | Yes, dev only | No snapshot | Gated by stateless mode and dev/debug mode                                                      |
| `{$await}`                                                                          | **No**        | Yes         | Compile error in a stateless build                                                              |
| `push_state()`                                                                      | **No**        | Yes         | Compile error when statically visible; hidden helper/dynamic pushes need manual review          |
| Per-token chat/streaming                                                            | **No**        | Yes         | Use WebSocket push; SSE is roadmap                                                              |
| Rooms / shared push channels                                                        | No            | No          | Not implemented on either tier                                                                  |

## Shared kernel

Ordinary events, render-time directives, forms, uploads, auth resolution, `wire.lock()`, optimistic UI, polling, and keyed regions are transport-agnostic. The same handler dispatch and `render_update` shape serve WebSocket, HTTP-session, and stateless transports.

## Server-push-only features

`{$await}` resolves a long-running awaitable on the server-owned timeline. It is stateful-only. `push_state()` similarly has nowhere to push in a one-shot request. `create_task()` is **not** a push feature: background work that writes a durable store is valid on stateless when the UI uses `@poll`.

## Build enforcement and blind spots

For a page and its statically resolvable component closure, `pywire build` rejects `{$await}` and directly visible `push_state()` calls when `stateless=True`. The same check runs during dev compilation.

The gate is syntactic. It cannot see calls hidden in imported helpers, dynamic dispatch, `push_state()` in template expressions, computed component paths, or installed third-party components. A resolvable component that violates the tier fails when that component compiles and names itself rather than the page. `create_task()` is deliberately not scanned.

## No-JS floor

`!no_interactive` pages expose a native form-POST fallback. On stateless, that POST executes the declared handler but carries no interactive snapshot, so state not persisted by the handler resets each request. This is safe but not state-continuous.

See [Stateless mode](/guides/stateless-mode/), [Optimistic UI and fast lists](/guides/stateless-interactions/), and [Long-running actions](/guides/long-running-actions/).
