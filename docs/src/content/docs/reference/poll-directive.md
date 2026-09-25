---
title: '@poll directive'
description: Reference for PyWire's timer-driven event handler.
---

`@poll` dispatches an event handler on an interval. It is a PyWire kernel primitive and works on both stateful and stateless tiers.

```pywire
<button @poll.every-500={refresh_job} $if={running}>
    Refresh every 500 ms
</button>
```

Use only one `@poll` attribute per element. The first interval is 1000 ms by default. `.every-<int>` sets the interval in milliseconds, with a minimum of 100; non-integer values or intervals below 100 are compile errors. The client-side default fallback only applies to hand-authored DOM attributes. On FaaS and edge runtimes, remember that a 100 ms floor can still create 10 requests per second per polled element, so choose the longest interval that still meets the product's freshness requirement.

The compiled attributes are `data-pw-poll` and `data-pw-poll-every`. Every tick uses the normal event dispatch path, including unwrapped argument lifting for expressions such as `@poll={refresh(item.id)}`.

## Lifecycle

- Timers are rescanned after every morph, navigation, and response.
- Conditional render is the stop rule: remove the polled element when the work is terminal.
- There is no `.while` condition in v1.
- A per-element in-flight flag skips ticks while that element's request is pending.
- The guard is best effort: any response clears in-flight flags globally. An empty update only clears those flags; it does not trigger a poll rescan.

## Example: bounded background work

```pywire
---
job_id = wire(None)
status = wire("queued")
---
<button @click={start_job}>Start</button>
<div $if={job_id.value is not None}>
    <progress $show={status.value not in ("done", "failed")}
              @poll.every-1000={refresh_job}></progress>
    <span>{status}</span>
</div>
```

`start_job` durably enqueues work; `refresh_job` reads the job store. `create_task()` is valid on stateless when it does not attempt server push. See the [long-running actions guide](/guides/long-running-actions/) for Cloudflare D1 + Queues, Firestore + Cloud Tasks, and local PostgreSQL patterns.
