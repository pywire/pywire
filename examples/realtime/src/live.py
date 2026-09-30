"""State shared by every connected page in this server process.

A ``wire()`` created at module level is one value for the whole process.
Every page that renders it re-renders when anyone writes it, including
pages whose users are idle: pywire pushes the update over their WebSocket.

Three rules keep shared wires correct:

1. Import this module under one name everywhere (``from live import ...``).
   ``src/`` is on ``sys.path``, so ``import live`` and ``import src.live``
   would load two copies with two separate sets of wires.
2. Write shared wires from the event loop, in plain functions without an
   ``await`` in the middle. The loop runs one handler at a time, so a
   read-modify-write with no ``await`` can't interleave with another user's.
   See ``race.wire`` for what happens when there is an ``await``.
3. This state is per process and lost on restart. With several workers,
   each has its own copy. Keep anything that matters in a database and use
   wires for what is live: presence, a chat backlog, counters, a cache.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Callable
from typing import Any

from pywire import derived, producer, wire

# --- Poll -----------------------------------------------------------------

QUESTION = "What should we build the next example with?"
OPTIONS = ("A database", "Background jobs", "Payments", "File uploads")

votes = wire({option: 0 for option in OPTIONS})


@derived
def total_votes() -> int:
    return sum(votes.values())


def vote(option: str) -> None:
    # Handler arguments come from the browser (``@click={cast_vote(o)}``
    # renders the value into the page and the client sends it back), so
    # validate them like any other request input.
    if option not in OPTIONS:
        raise ValueError(f"Unknown option {option!r}")
    votes[option] += 1


def reset_votes() -> None:
    votes.value = {option: 0 for option in OPTIONS}


# --- Presence -------------------------------------------------------------

# visitor id -> display name. Pages add themselves in @mount and remove
# themselves in @unmount, which runs when the tab closes or navigates away.
online = wire({})


def join(visitor: str, name: str) -> None:
    online[visitor] = name


def leave(visitor: str) -> None:
    online.pop(visitor, None)


# --- Chat -----------------------------------------------------------------

MAX_MESSAGES = 50
MAX_LENGTH = 500

messages = wire([])
_message_ids = itertools.count(1)


def post(author: str, text: str) -> None:
    text = text.strip()[:MAX_LENGTH]
    if not text:
        return
    messages.append(
        {
            "id": next(_message_ids),
            "author": author,
            "text": text,
            "at": time.strftime("%H:%M"),
        }
    )
    # Keep the backlog bounded: every connected page holds a reference to
    # this list, and every new message re-renders it for everyone.
    if len(messages) > MAX_MESSAGES:
        messages.pop(0)


# --- Server clock ---------------------------------------------------------


def _clock(set_value: Callable[[Any], None]) -> Callable[[], None]:
    """Push the time every second.

    A producer starts on its first read, which happens while a page renders,
    so there is a running event loop to put the task on. Prefer an asyncio
    task to a thread; if you do use a thread, ``set_value`` is thread-safe.
    """

    async def tick() -> None:
        while True:
            set_value(time.strftime("%H:%M:%S"))
            await asyncio.sleep(1)

    task = asyncio.get_running_loop().create_task(tick())
    return task.cancel


server_time = producer("--:--:--", _clock)
