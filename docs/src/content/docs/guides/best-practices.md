---
title: Building Real Apps
description: How to structure a pywire app that has a database, users, an API and live pages, and the details that trip people up.
---

This guide collects the practices the [example apps](https://github.com/pywire/pywire/tree/main/examples) follow. The [taskboard example](https://github.com/pywire/pywire/tree/main/examples/taskboard) puts all of them in one FastAPI + pywire app, with tests.

## Structure

Keep the application in a package next to your pages, and make pages thin:

```
src/
  main.py            the ASGI app: FastAPI (or PyWire alone), mounts, lifespan
  myapp/
    settings.py      configuration from the environment
    db.py            engine and sessions
    models.py        tables
    schemas.py       Pydantic models for input and output
    services.py      every read and write, with access checks
    live.py          shared wires, if pages update live
    api.py           JSON routes, if you have an API
  pages/             .wire pages
  components/        .wire components
```

- **Put rules in services, not pages.** A service function takes the current user and the input, checks access first, and does the work. A page handler and an API route both call it, so they can't disagree about who may do what. Pages never call your own API over HTTP.
- **Raise errors that know their field.** A `ServiceError(message, field="assignee_id")` becomes `form.assignee_id.error = message` on a page and `{"detail": ..., "field": ...}` in the API.
- **Import app code by one name.** `src/` is on `sys.path` for pages, so `from myapp import services` works. Importing the same file as `src.myapp.services` elsewhere loads a second copy, with its own module-level state.

## Where state lives

| Kind                             | Lives                         | Use it for                                                       |
| -------------------------------- | ----------------------------- | ---------------------------------------------------------------- |
| `wire()` in a page's frontmatter | One tab                       | Form input, filters, open/closed, anything about this view       |
| `wire()` at module level         | One server process, every tab | Live data many people watch: presence, a board's tasks, counters |
| The database                     | Everywhere, survives restarts | Anything that matters                                            |

A module-level wire is a cache of what's live, not the source of truth. When data changes, write the database, commit, then update the shared wire from what was committed. Every page rendering that wire re-renders and receives the change over its WebSocket, including pages whose users are idle.

```python
# myapp/live.py
tasks_by_board: dict[int, WireList] = {}

async def board_changed(board_id: int) -> None:
    if board_id not in tasks_by_board:
        return  # nobody has it open
    async with db.session() as s:
        rows = await services.load_tasks(s, board_id)
    tasks_by_board[board_id].value = [t.model_dump() for t in rows]  # one write, one re-render
```

Call it after the commit, never before: a page that re-reads the database before your commit lands sees the old data. The taskboard's `db.after_commit()` runs callbacks once the transaction has committed.

### Concurrency

The rules from [Reactivity](/docs/concepts/reactivity/#concurrency) in short:

- One event loop runs every handler in the process. A read-modify-write with no `await` in the middle can't interleave with another user's.
- A read, an `await`, then a write can lose updates. Hold an `asyncio.Lock`, or let the database do the update (`UPDATE ... SET n = n + 1`).
- Module state is per process. With several workers, each has its own copy: run one worker, or publish changes through Redis or Postgres `LISTEN/NOTIFY` and apply them in every worker.

## Pages

### Loading data

Load in `@init`. It runs before the first render, for the HTML and again for the page instance that serves the live connection, so keep it to reads.

```python
@init
async def load():
    async with db.session() as s:
        board = await services.get_board(s, actor_from(self.user), int(params.board_id))
    ...
```

Check access before you touch shared state. Wrapping shared data in `$if={allowed}` in the template is not a check: the data is already in the page.

### Handlers

- **Arguments come from the browser.** `@click={move(task["id"], "done")}` renders both values into the page, and the browser sends them back. A user can send anything. Parse them and let the service decide whether this user may act on that id.
- **Resolve the user on every call.** Call `actor_from(self.user)` in each handler rather than storing the user at load. If the user signs out elsewhere, the next action fails instead of running as them.
- **Catch service errors and show them.** A handler that raises shows the error page; one that catches `ServiceError` can put the message on the form.

```python
async def add_task(data: TaskIn):
    try:
        async with db.session() as s:
            await services.create_task(s, actor_from(self.user), board_id, data)
    except ServiceError as e:
        if e.field:
            task_form[e.field].error = e.message
        else:
            task_form.error = e.message
        return
    task_form.reset()
```

### Forms

Use the same Pydantic model for the API body and `form(Model)`. Field rules (lengths, types, choices) are written once, reach the browser as `required`, `maxlength` and friends, and are enforced again on the server. Rules that need the database go in the service. See [Forms & Validation](/docs/guides/forms/).

### Undo in `@unmount` what `@mount` did

`@unmount` runs when the tab closes or navigates away. Anything the page added to shared state (joined a presence list) or subscribed to (an `effect()` on a shared wire) must be taken back there, or it outlives the tab.

```python
_watch = None

@init
async def load():
    global _watch
    ...
    _watch = effect(announce)

@unmount
def leave():
    live.viewers.pop(visitor, None)
    if _watch is not None:
        _watch.dispose()
```

An effect on a shared wire runs inside whichever handler wrote the wire, possibly another user's. Keep it short and only write the page's own wires from it.

### Private names

Frontmatter names starting with `_` are left out of session snapshots. Use them for handles that can't be serialized (a feed object, an effect, a client), and assign them from hooks with `global`.

## Users and access

- **Authorization data lives in your tables.** Store roles and memberships yourself and check them in services. Don't grant access from claims a user could have supplied at registration.
- **Pages use the session, the API uses tokens.** Pages get `self.user` from pywire-auth's session cookie. Give the JSON API bearer tokens (`LocalIdP.issue_id_token`) so it needs no cookies and no CSRF protection. Both become the same "actor" object before they reach services.
- **Add `!auth` to pages that need a user, and still check in handlers.** `!auth` guards the page load. Handlers that call `actor_from(self.user)` stay safe even if the user changes while the page is open.

## Files

- Store uploads through a `FileStore` (`LocalStore` in development, `ObjectStore.from_url("s3://...")` in production). Nothing else changes when you switch.
- The browser's filename and content type are hints. Decide what a file is from its bytes, pick the key yourself, and serve files with `X-Content-Type-Options: nosniff`.

## Live features outside pywire

Most live updates need nothing but shared wires. For data that changes many times a second and only needs drawing, like cursor positions, a page handler would re-render the page on every message. Serve a plain WebSocket from FastAPI or Starlette next to pywire's own and let a small script on the page talk to it:

```python
@app.websocket("/api/boards/{board_id}/cursors")
async def cursors(ws: WebSocket, board_id: int, token: str = ""):
    actor = actor_from_socket_token(token, board_id)
    if actor is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    ...
```

Browsers can't set headers on a WebSocket, so the page renders a short-lived ticket scoped to that board into the HTML for the script to send. Keep the element the script draws into marked `$permanent`, so pywire's updates leave its children alone. Inline scripts run again after each update that includes them, so make the script start once and stop on `pywire:beforenavigate`.

## Testing

Pages can be tested without a browser: open pywire's WebSocket with Starlette's `TestClient` and speak its protocol, one connection per simulated tab. The [realtime](https://github.com/pywire/pywire/tree/main/examples/realtime/tests) and [taskboard](https://github.com/pywire/pywire/tree/main/examples/taskboard/tests) examples have helpers for opening a tab, firing a handler and waiting for a pushed update. Use one `TestClient` for the whole session so all tabs share one event loop, as they do in a real server.

## Details that surprise people

- **`@derived` values that hold a dict or list need `.value` for methods.** `people.value.values()`, not `people.values()`. Indexing, `len()` and iteration work without it.
- **`@mount` runs after the first HTML reaches the browser.** Writes it makes arrive as a push right after.
- **Keep shared lists bounded.** Every page that renders a shared list re-renders it on each change.
- **A `<dialog>` opened with `show_modal()` needs `open={...}` in the template** mirroring your own open state, or a re-render while it's open removes the attribute.
- **Inside a component's functions, `props` is still the decorator.** Pass `props.name` into helpers as an argument.
