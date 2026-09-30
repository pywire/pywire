# Taskboard

A team task board: FastAPI serves a JSON API and a raw WebSocket, pywire serves the pages, and both call the same service layer. Boards update live for everyone who has them open, whether the change came from a page or from the API.

```sh
cd examples/taskboard
cp .env.example .env        # then fill in the two secrets
uv run pywire dev src.main:app
uv run pytest
```

Open two browsers (or one normal and one private window), create an account in each, make a board in one and invite the other.

## What it uses

| Feature | Where |
| --- | --- |
| FastAPI host with pywire mounted at `/` | `src/main.py` |
| JSON API with bearer tokens | `src/taskboard/api.py`, `identity.py` |
| Raw WebSocket next to pywire's (live cursors) | `api.py` (`/api/boards/{id}/cursors`), script at the end of `boards/[board_id].wire` |
| Service layer shared by pages and API | `src/taskboard/services.py` |
| SQLAlchemy async, one engine shared with pywire-auth | `db.py`, `models.py` |
| pywire-auth: register, sign in, sign out, `!auth` pages | `main.py`, `login.wire`, `register.wire`, `__layout__.wire` |
| `form(Model)` with the same Pydantic model as the API | `schemas.TaskIn`, `boards/[board_id].wire` |
| Multi-step `wizard()` with list rows | `boards/new.wire` |
| File upload checked by content, stored in a `FileStore` | `profile.wire`, `services.save_profile` |
| Shared module-level wires, one set per board | `src/taskboard/live.py` |
| `@derived`, `@effect`, `@mount`, `@unmount` | `boards/[board_id].wire` |
| `ref[DialogElement]` for an edit dialog | `boards/[board_id].wire` |
| A display-only component with props | `src/components/avatar.wire` |

## How it fits together

```
browser ──► FastAPI app ──► /api/*, /files/*   (api.py)      ─┐
                        └─► everything else    (pywire pages) ─┤
                                                               ▼
                                                   services.py (rules, access)
                                                               │ after commit
                                                               ▼
                                                   live.py (shared wires) ──► every open board page
```

- **One service layer.** Every read and write goes through `services`, which takes an `Actor` and checks access first. Pages and API routes are a few lines each: turn the request into a call, turn the result or the `ServiceError` into a response. Nothing calls its own API over HTTP.
- **One model per input.** `TaskIn` is the FastAPI request body and the model behind `form(TaskIn)`. Field rules (lengths, types, the status enum) are written once and reach the browser as `required`, `maxlength` and so on. Rules that need the database, like "the assignee must be on this board", live in the service and come back as a `ServiceError` with a `field`, which pages put on that field and the API returns as JSON.
- **Publish after commit.** A service registers `live.board_changed` with `db.after_commit`, so other pages re-read the database only once the change is visible to them. `live` reloads the board once and writes the result into that board's shared wires; every page showing the board re-renders from them, so a hundred viewers cost one query, not a hundred.
- **Identity.** Pages get `self.user` from the session cookie. The API takes `Authorization: Bearer <token>` (make one on the profile page), so it needs no cookies and no CSRF protection. The cursor socket gets a short-lived ticket for one board, rendered into the page. All three become an `Actor`, which is all services see.
- **Authorization lives in our tables.** Board roles are in `memberships`, never in claims from pywire-auth's registration form.

## Things to know

- **Run one worker.** The live board state and the cursor rooms are in process memory, so `pywire run src.main:app --workers 1`. For more workers, publish board ids through Redis or Postgres `LISTEN/NOTIFY` and call `live.board_changed` in each worker when one arrives. Nothing else changes. Uploads use a `LocalStore`; with several machines, switch to `ObjectStore.from_url("s3://...")`.
- **Check access before touching shared state.** The board page reads `live.feed()` only after `services.get_board` succeeded. Rendering `{$if allowed}` around shared data is not a check: the data would still be loaded into the page.
- **Private names stay on the server.** Frontmatter names starting with `_` (`_feed`, `_board_id`) aren't saved in session snapshots. Use them for handles like the feed or an effect.
- **Undo in `@unmount` what `@mount` did.** The board page adds itself to the board's viewers and starts an `@effect` on the shared activity wire; `@unmount` removes it and disposes the effect. Without that, a closed tab stays "here" and its effect keeps running.
- **An `@effect` on shared state runs inside the writer's handler.** When Ada moves a task, every open board's effect runs during Ada's request. Keep effects short and only write the page's own wires from them.
- **Handler arguments come from the browser.** `@click={move(task["id"], "done")}` renders the id and status into the page; the client can send anything back. `move` parses both and the service checks the task is on a board the user belongs to.
- **Resolve the user on every call.** Handlers call `actor_from(self.user)` each time instead of storing the actor at load. If the user signs out in another tab, the next action fails instead of running as them.
- **Don't trust upload names or types.** The browser's filename and content type are hints. `save_profile` reads the first bytes to decide what the file is, picks the key itself, and the avatar route serves only keys it generated, with `nosniff`.
- **Derived dicts and lists need `.value` for methods.** `people.value.values()`, not `people.values()`. Indexing and iteration work without it.
- **A dialog opened with `show_modal()` needs `open={...}` in the template** so a re-render while it's open doesn't remove the attribute. The board's edit dialog shows the pattern.
- **Inline scripts run again after each update that includes them.** The cursor script checks whether it's already running for this board and stops itself on `pywire:beforenavigate`.

## Layout

```
src/
  main.py              FastAPI app, pywire mounted, one lifespan
  taskboard/           the application (imported as `taskboard`)
    settings.py        configuration from the environment
    db.py              engine, sessions, after-commit hooks
    models.py          tables
    schemas.py         Pydantic models for the API and the forms
    errors.py          ServiceError and friends
    identity.py        Actor, bearer tokens, socket tickets
    services.py        every read and write, with access checks
    live.py            shared wires per board
    api.py             JSON routes, avatar files, cursor WebSocket
  pages/               pywire pages
  components/          pywire components
static/app.css
tests/                 API, pages over the WebSocket, services
```
