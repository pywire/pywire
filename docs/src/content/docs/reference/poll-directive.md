---
title: '@poll directive'
description: Reference for PyWire's timer-driven event handler.
---

`@poll` dispatches an event handler on an interval. It is a PyWire kernel primitive and works on both stateful and stateless tiers.

```pywire
<button @poll={refresh_job} @poll.every-500ms={refresh_job} $if={running}>
    Refresh
</button>
```

Use only one `@poll` attribute per element. The first interval is 1000 ms by default. `.every-<ms>` changes it; invalid or non-positive values use the default.

The compiled attributes are `data-pw-poll` and `data-pw-poll-every`. Every tick uses the normal event dispatch path, including unwrapped argument lifting for expressions such as `@poll={refresh(item.id)}`.

## Lifecycle

- Timers are rescanned after every morph, navigation, and response.
- Conditional render is the stop rule: remove the polled element when the work is terminal.
- There is no `.while` condition in v1.
- A per-element in-flight flag skips ticks while that element's request is pending.
- The guard is best effort: any response clears in-flight flags globally.

## Example: bounded background work

```pywire
---
job_id = wire(None)
status = wire("queued")
---
<button @click={start_job}>Start</button>
<div $if={job_id.value is not None}>
    <progress $show={status.value not in ("done", "failed")}
              @poll.every-1000ms={refresh_job}></progress>
    <span>{status}</span>
</div>
```

`start_job` durably enqueues work; `refresh_job` reads the job store. `create_task()` is valid on stateless when it does not attempt server push. See the [long-running actions guide](/guides/long-running-actions/) for Cloudflare D1 + Queues, Firestore + Cloud Tasks, and local PostgreSQL patterns.
