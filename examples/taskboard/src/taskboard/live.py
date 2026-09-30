"""Live board state shared by every open page in this process.

When a board changes (from a page, the JSON API, anything that goes through
``services``), ``board_changed`` reloads that board once and writes the
result into the board's shared wires. Every page showing the board renders
from those wires, so all of them update, and the database is read once per
change rather than once per viewer.

Pages must check access (``services.get_board``) before calling ``feed()``:
the feed holds every task of the board.

This is per process. With several workers, publish ``board_id`` through
Redis or Postgres ``LISTEN/NOTIFY`` and call ``board_changed`` in each
worker when it arrives; nothing else changes.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from pywire import wire
from pywire.core.wire import WireDict, WireList


@dataclass
class BoardFeed:
    tasks: WireList = field(default_factory=lambda: wire([]))
    members: WireList = field(default_factory=lambda: wire([]))
    # The latest change: {"seq", "actor_id", "text"}. Pages watch it with an
    # @effect to show "Ada moved X to Done" to everyone but Ada.
    activity: WireDict = field(default_factory=lambda: wire({}))
    # Who has the board open right now: visitor id -> name.
    viewers: WireDict = field(default_factory=lambda: wire({}))
    loaded: bool = False


_feeds: dict[int, BoardFeed] = {}
_seq = itertools.count(1)


def feed(board_id: int) -> BoardFeed:
    return _feeds.setdefault(board_id, BoardFeed())


async def load(board_id: int) -> BoardFeed:
    """The board's feed, read from the database the first time it's needed."""
    board = feed(board_id)
    if not board.loaded:
        await _reload(board_id)
    return board


async def board_changed(board_id: int, actor_id: str, text: str) -> None:
    """Called by services after a change to the board is committed."""
    if board_id not in _feeds:
        return  # nobody has it open; the next viewer loads it fresh
    await _reload(board_id)
    _feeds[board_id].activity.value = {
        "seq": next(_seq),
        "actor_id": actor_id,
        "text": text,
    }


async def _reload(board_id: int) -> None:
    from taskboard import db, services

    async with db.session() as s:
        tasks = await services.load_tasks(s, board_id)
        members = await services.load_members(s, board_id)
    board = feed(board_id)
    # One write each: every page showing the list re-renders once.
    board.tasks.value = [t.model_dump(mode="json") for t in tasks]
    board.members.value = [m.model_dump() for m in members]
    board.loaded = True
