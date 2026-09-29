# Realtime

State shared between everyone connected to one server: a live poll, a list of who is here, a chat room, a server clock, and a page that shows how races happen and how to prevent them.

```sh
cd examples/realtime
uv run pywire dev          # or: uv run pywire run --workers 1
uv run pytest              # two simulated tabs per test
```

Open two browser windows side by side. Vote, chat, or open and close a tab: the other window updates without doing anything.

## Files

| File | What it shows |
| --- | --- |
| `src/live.py` | Module-level `wire()`s shared by every page, a `@derived` total, and a `producer()` clock fed by an asyncio task |
| `src/counter.py` | Shared state backed by slow async storage, with and without an `asyncio.Lock` |
| `src/pages/index.wire` | Poll and presence: `@mount` and `@unmount` add and remove the visitor, keyed `{$for}` for the list of people |
| `src/pages/chat.wire` | Chat: `$bind` on a wire, a plain `@submit.prevent` form, a bounded shared list |
| `src/pages/race.wire` | Ten concurrent increments, lost updates without a lock |
| `tests/` | Drives pages over the WebSocket protocol with two sessions at once |

## How shared state works

A `wire()` created at module level is one value for the whole server process. A page that renders it subscribes to it, and when anyone writes it, pywire re-renders that part of every subscribed page and pushes it over the page's WebSocket. Frontmatter variables (`my_vote = wire("")` inside a `.wire` file) are per tab.

Writes are safe without locks as long as the handler doesn't `await` between reading and writing. The event loop runs one handler at a time, so `votes[option] += 1` can't interleave with another user's vote. A handler that reads, awaits, then writes can lose updates (see `race.wire`); hold an `asyncio.Lock` or, better, let the database do the update atomically.

## Things to know

- **One process only.** `pywire run` starts one worker per CPU core (×2 +1) by default, and each worker has its own copy of module state, so two users on different workers never see each other. Run this example with `--workers 1`. A real app keeps shared data in a database and uses Redis (or Postgres `LISTEN/NOTIFY`) to tell other workers to refresh.
- **Import shared modules by one name.** `src/` is on `sys.path`, so `import live` works from pages. Importing the same file as `src.live` somewhere else loads a second copy with its own wires.
- **Handler arguments are client input.** `@click={cast(option)}` renders `option` into the page and the browser sends it back when clicked. A client can send anything, so `live.vote()` checks it.
- **`@mount` runs after the first render reaches the browser**, so the first HTML a visitor gets doesn't include them in the presence list yet; the push that follows does.
- **Keep shared lists bounded.** Every page that shows `live.messages` re-renders it on each new message, so the chat keeps the last 50.
- **Long-polling and WebTransport clients** get shared updates on their next event rather than immediately ([#361](https://github.com/pywire/pywire/issues/361)).
