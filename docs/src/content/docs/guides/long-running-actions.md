---
title: Long-running actions
description: Model bounded background work with @poll and choose the stateful tier when the server owns a live timeline.
---

`@poll` is a timer-driven event, not a DOM event. It dispatches through the same handler path on stateful and stateless tiers:

```pywire
---
job_id = wire(None)
status = wire("queued")
---

<button @click={start_export} @poll.every-1000={refresh_job} $if={status.value not in ("done", "failed")}>
    {status}
</button>
```

`start_export` writes a job record and starts background work; `refresh_job` reads that record into ordinary page state. Handlers receive **unwrapped values**, not live Wire objects.

The element is a conditional-render stop rule: when the handler reaches a terminal state, render the element conditionally so it unmounts. PyWire has no `.while` condition in v1. The timer rescans after morphs and removes unmounted elements. Use an explicit interval (for example `.every-500ms` or `.every-2000ms`); the default is 1000 ms.

The overlap guard is **best effort in v1**: a poll element skips a tick while its request is in flight, but any response clears the in-flight flags globally. Do not treat this as a distributed scheduling guarantee. Protect the job with an idempotent store operation.

## Per-platform cookbook

| Platform        | Submit work                              | Persist status                     | Poll read                  |
| --------------- | ---------------------------------------- | ---------------------------------- | -------------------------- |
| Cloudflare      | Enqueue a Cloudflare Queue message       | D1 row keyed by job ID             | D1 query by job ID         |
| GCP             | Trigger or enqueue a Cloud Task          | Firestore document keyed by job ID | Firestore query by job ID  |
| Local/container | `create_task()` and a local queue/worker | PostgreSQL jobs table              | PostgreSQL query by job ID |

For example, the handler shape is the same everywhere:

```python
def start_export():
    job_id.value = jobs.enqueue(user_id=user_id.value)
    status.value = "queued"

async def refresh_job():
    job = await jobs.find(job_id.value)
    if job is None:
        status.value = "queued"
    else:
        status.value = job.status
        if job.result_url:
            result_url.value = job.result_url
```

`create_task()` is not a tier signal. It is valid on stateless when the task writes a durable store and does not try to push to an open client.

## When to use the stateful tier

Use stateful when the server must push a live timeline: per-token chat/streaming, arbitrary progress, or `{$await}`. Stateful WebSockets provide client/server push. For bounded waits, use `@poll` on either tier. SSE is roadmap work, not shipped.

**`{$await}` is stateful-only.** `pywire build` rejects it in a `PyWire(stateless=True)` app. Use a job store plus `@poll`, or remove `stateless=True`.
