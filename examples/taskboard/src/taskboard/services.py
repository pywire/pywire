"""Everything the app can do, for a given ``Actor``.

Pages and API routes are thin: they turn a request into a call here and the
result (or a ``ServiceError``) into a response. Rules for what a user may
see and do live here and only here, so a page handler, a JSON call and a
WebSocket message are held to the same checks.

Every function takes the session first and the actor second, checks access
before anything else, and never trusts ids that came from the client: a
task id in a click handler or a URL is just a request to look it up.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pywire.storage import LocalStore
from taskboard import live
from taskboard.db import after_commit
from taskboard.errors import Forbidden, Invalid, NotFound
from taskboard.identity import Actor, store
from taskboard.models import Board, Membership, Profile, Task
from taskboard.schemas import (
    BoardOut,
    MemberOut,
    NewBoard,
    ProfileIn,
    Status,
    TaskIn,
    TaskOut,
)
from taskboard.settings import settings

# Swap for ObjectStore.from_url("s3://...") in production; nothing else changes.
avatars = LocalStore(settings.upload_dir / "avatars")

# --- Access ---------------------------------------------------------------


async def _membership(s: AsyncSession, actor: Actor, board_id: int) -> Membership:
    membership = await s.scalar(
        select(Membership).where(
            Membership.board_id == board_id, Membership.user_id == actor.id
        )
    )
    if membership is None:
        # Same answer for "doesn't exist" and "not yours": don't leak ids.
        raise NotFound("Board not found")
    return membership


async def _task(s: AsyncSession, actor: Actor, task_id: int) -> Task:
    task = await s.get(Task, task_id)
    if task is None:
        raise NotFound("Task not found")
    await _membership(s, actor, task.board_id)
    return task


async def _check_assignee(s: AsyncSession, board_id: int, assignee: str | None) -> None:
    if assignee is None:
        return
    member = await s.scalar(
        select(Membership.id).where(
            Membership.board_id == board_id, Membership.user_id == assignee
        )
    )
    if member is None:
        raise Invalid("Pick someone on this board", field="assignee_id")


def _changed(s: AsyncSession, board_id: int, actor: Actor, text: str) -> None:
    after_commit(s, lambda: live.board_changed(board_id, actor.id, text))


# --- Boards ---------------------------------------------------------------


async def list_boards(s: AsyncSession, actor: Actor) -> list[BoardOut]:
    rows = await s.scalars(
        select(Board)
        .join(Membership, Membership.board_id == Board.id)
        .where(Membership.user_id == actor.id)
        .order_by(Board.name)
    )
    return [BoardOut.model_validate(b) for b in rows]


async def get_board(s: AsyncSession, actor: Actor, board_id: int) -> BoardOut:
    await _membership(s, actor, board_id)
    board = await s.get(Board, board_id)
    assert board is not None
    return BoardOut.model_validate(board)


async def is_owner(s: AsyncSession, actor: Actor, board_id: int) -> bool:
    return (await _membership(s, actor, board_id)).role == "owner"


async def _user_by_email(email: str) -> tuple[str, str] | None:
    record = await store.find_by_provider("local", str(email))
    if record is None:
        return None
    return f"local:{record['user_id']}", record.get("name") or str(email)


async def create_board(s: AsyncSession, actor: Actor, data: NewBoard) -> BoardOut:
    invitees = []
    for i, invite in enumerate(data.team.invites):
        found = await _user_by_email(invite.email)
        if found is None:
            raise Invalid(
                "No account uses this email yet", field=f"team.invites.{i}.email"
            )
        invitees.append(found)

    board = Board(name=data.basics.name, description=data.basics.description)
    s.add(board)
    await s.flush()
    s.add(
        Membership(board_id=board.id, user_id=actor.id, name=actor.name, role="owner")
    )
    for user_id, name in dict(invitees).items():
        if user_id != actor.id:
            s.add(
                Membership(board_id=board.id, user_id=user_id, name=name, role="member")
            )
    return BoardOut.model_validate(board)


async def list_members(s: AsyncSession, actor: Actor, board_id: int) -> list[MemberOut]:
    await _membership(s, actor, board_id)
    return await load_members(s, board_id)


async def add_member(
    s: AsyncSession, actor: Actor, board_id: int, email: str
) -> MemberOut:
    if (await _membership(s, actor, board_id)).role != "owner":
        raise Forbidden("Only the board's owner can add people")
    found = await _user_by_email(email)
    if found is None:
        raise Invalid("No account uses this email yet", field="email")
    user_id, name = found
    existing = await s.scalar(
        select(Membership).where(
            Membership.board_id == board_id, Membership.user_id == user_id
        )
    )
    if existing is not None:
        raise Invalid("Already on this board", field="email")
    s.add(Membership(board_id=board_id, user_id=user_id, name=name, role="member"))
    _changed(s, board_id, actor, f"{actor.name} added {name}")
    return MemberOut(user_id=user_id, name=name, role="member")


# --- Tasks ----------------------------------------------------------------


async def list_tasks(s: AsyncSession, actor: Actor, board_id: int) -> list[TaskOut]:
    await _membership(s, actor, board_id)
    return await load_tasks(s, board_id)


async def load_tasks(s: AsyncSession, board_id: int) -> list[TaskOut]:
    """All tasks of a board, without an access check. For ``live`` only."""
    rows = await s.scalars(
        select(Task).where(Task.board_id == board_id).order_by(Task.updated_at.desc())
    )
    return [TaskOut.model_validate(t) for t in rows]


async def load_members(s: AsyncSession, board_id: int) -> list[MemberOut]:
    """All members of a board, without an access check. For ``live`` only."""
    rows = await s.execute(
        select(Membership, Profile.avatar_key)
        .outerjoin(Profile, Profile.user_id == Membership.user_id)
        .where(Membership.board_id == board_id)
        .order_by(Membership.name)
    )
    return [
        MemberOut(user_id=m.user_id, name=m.name, role=m.role, avatar_key=avatar)
        for m, avatar in rows
    ]


async def create_task(
    s: AsyncSession, actor: Actor, board_id: int, data: TaskIn
) -> TaskOut:
    await _membership(s, actor, board_id)
    await _check_assignee(s, board_id, data.assignee_id)
    task = Task(board_id=board_id, created_by=actor.id, **data.model_dump())
    s.add(task)
    await s.flush()
    _changed(s, board_id, actor, f"{actor.name} added “{task.title}”")
    return TaskOut.model_validate(task)


async def update_task(
    s: AsyncSession, actor: Actor, task_id: int, data: TaskIn
) -> TaskOut:
    task = await _task(s, actor, task_id)
    await _check_assignee(s, task.board_id, data.assignee_id)
    for key, value in data.model_dump().items():
        setattr(task, key, value)
    await s.flush()
    _changed(s, task.board_id, actor, f"{actor.name} edited “{task.title}”")
    return TaskOut.model_validate(task)


async def move_task(
    s: AsyncSession, actor: Actor, task_id: int, status: Status
) -> TaskOut:
    task = await _task(s, actor, task_id)
    if task.status != status.value:
        task.status = status.value
        await s.flush()
        _changed(
            s,
            task.board_id,
            actor,
            f"{actor.name} moved “{task.title}” to {status.label}",
        )
    return TaskOut.model_validate(task)


async def delete_task(s: AsyncSession, actor: Actor, task_id: int) -> None:
    task = await _task(s, actor, task_id)
    await s.delete(task)
    _changed(s, task.board_id, actor, f"{actor.name} deleted “{task.title}”")


# --- Profile --------------------------------------------------------------


async def get_profile(s: AsyncSession, actor: Actor) -> Profile:
    profile = await s.get(Profile, actor.id)
    return profile or Profile(user_id=actor.id, display_name=actor.name)


def _image_extension(head: bytes) -> str | None:
    """The real type of an image, from its first bytes.

    The browser's filename and content type are only hints (anyone can send
    a script called cat.png), so decide from the bytes.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


async def save_profile(s: AsyncSession, actor: Actor, data: ProfileIn) -> Profile:
    profile = await s.get(Profile, actor.id)
    if profile is None:
        profile = Profile(user_id=actor.id, display_name=data.display_name)
        s.add(profile)
    profile.display_name = data.display_name
    if data.avatar is not None:
        content = await data.avatar.read()  # at most 1 MB: UploadField caps it
        extension = _image_extension(content[:12])
        if extension is None:
            raise Invalid("Use a PNG, JPEG or WebP image", field="avatar")
        old, profile.avatar_key = profile.avatar_key, secrets.token_hex(16) + extension
        await avatars.put(profile.avatar_key, content)
        if old:
            after_commit(s, lambda: avatars.delete(old))
    # Keep the name other members see in step with the profile.
    memberships = await s.scalars(
        select(Membership).where(Membership.user_id == actor.id)
    )
    for m in memberships:
        m.name = data.display_name
        _changed(s, m.board_id, actor, f"{data.display_name} updated their profile")
    return profile
