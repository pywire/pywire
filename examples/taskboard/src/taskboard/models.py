"""Tables. Users live in pywire-auth's tables; we store their ids."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from taskboard.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("board_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"))
    # pywire-auth principal id, e.g. "local:3f0c..."
    user_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10))  # "owner" | "member"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("boards.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="todo")
    due: Mapped[date | None] = mapped_column(default=None)
    assignee_id: Mapped[str | None] = mapped_column(String(80), default=None)
    created_by: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    avatar_key: Mapped[str | None] = mapped_column(String(200), default=None)
