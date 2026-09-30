"""Pydantic models shared by the JSON API and the page forms.

The same ``TaskIn`` is FastAPI's request body for ``POST /api/boards/{id}/tasks``
and the model behind ``form(TaskIn)`` on the board page, so the API, the
browser's validation attributes and the server's checks can't drift apart.
Rules that need the database (is the assignee on this board?) live in
``services``, which both paths call.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from pywire.forms import Upload, UploadField


class Status(str, Enum):
    todo = "todo"
    doing = "doing"
    done = "done"

    @property
    def label(self) -> str:
        return {"todo": "To do", "doing": "Doing", "done": "Done"}[self.value]


# --- Tasks ----------------------------------------------------------------


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)
    status: Status = Status.todo
    due: date | None = None
    assignee_id: str | None = Field(default=None, title="Assignee")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    board_id: int
    title: str
    notes: str
    status: Status
    due: date | None
    assignee_id: str | None
    updated_at: datetime


class Move(BaseModel):
    status: Status


# --- Boards ---------------------------------------------------------------


class BoardBasics(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class Invitee(BaseModel):
    email: EmailStr


class Team(BaseModel):
    invites: list[Invitee] = Field(default_factory=list, max_length=10)


class NewBoard(BaseModel):
    """A board and the people to invite. One wizard step per field."""

    basics: BoardBasics
    team: Team


class BoardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str


class MemberOut(BaseModel):
    user_id: str
    name: str
    role: str
    avatar_key: str | None = None


class InviteIn(BaseModel):
    email: EmailStr


# --- Profile --------------------------------------------------------------


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    avatar: Annotated[
        Upload | None,
        UploadField(accept="image/png, image/jpeg, image/webp", max_size="1 MB"),
    ] = None
