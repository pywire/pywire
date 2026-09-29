"""The JSON API and the raw WebSocket, as FastAPI routes.

Each route is: authenticate (a dependency), open a session (a dependency),
call one service, return its result. ``ServiceError``s become JSON errors
through the handler ``install`` registers.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from taskboard import services
from taskboard.db import get_session
from taskboard.errors import NotAuthenticated, ServiceError
from taskboard.identity import Actor, actor_from_socket_token, actor_from_token
from taskboard.schemas import BoardOut, Move, NewBoard, TaskIn, TaskOut


async def current_actor(authorization: Annotated[str, Header()] = "") -> Actor:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise NotAuthenticated("Send Authorization: Bearer <token>")
    return await actor_from_token(token)


Me = Annotated[Actor, Depends(current_actor)]
Db = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/api")


@router.get("/me")
async def me(actor: Me) -> dict:
    return {"id": actor.id, "name": actor.name}


@router.get("/boards")
async def list_boards(actor: Me, db: Db) -> list[BoardOut]:
    return await services.list_boards(db, actor)


@router.post("/boards", status_code=201)
async def create_board(data: NewBoard, actor: Me, db: Db) -> BoardOut:
    return await services.create_board(db, actor, data)


@router.get("/boards/{board_id}/tasks")
async def list_tasks(board_id: int, actor: Me, db: Db) -> list[TaskOut]:
    return await services.list_tasks(db, actor, board_id)


@router.post("/boards/{board_id}/tasks", status_code=201)
async def create_task(board_id: int, data: TaskIn, actor: Me, db: Db) -> TaskOut:
    return await services.create_task(db, actor, board_id, data)


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, data: TaskIn, actor: Me, db: Db) -> TaskOut:
    return await services.update_task(db, actor, task_id, data)


@router.post("/tasks/{task_id}/move")
async def move_task(task_id: int, data: Move, actor: Me, db: Db) -> TaskOut:
    return await services.move_task(db, actor, task_id, data.status)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, actor: Me, db: Db) -> None:
    await services.delete_task(db, actor, task_id)


# --- Files ----------------------------------------------------------------

_AVATAR_KEY = re.compile(r"^[0-9a-f]{32}\.(png|jpe?g|webp)$")
_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

files = APIRouter()


@files.get("/files/avatars/{key}")
async def avatar(key: str) -> Response:
    # Keys are random, so knowing one is the permission to see it. That keeps
    # <img src> working without cookies on the API. Use signed URLs for
    # anything more private than an avatar.
    if not _AVATAR_KEY.match(key) or not await services.avatars.exists(key):
        return Response(status_code=404)
    return Response(
        await services.avatars.get(key),
        media_type=_TYPES[key.rsplit(".", 1)[1]],
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- Cursors: a raw WebSocket next to pywire's own -------------------------
#
# Cursor positions change dozens of times a second, matter for a moment, and
# only need to be drawn, not stored. Sending them through page handlers would
# re-render the page on every mouse move. A small script on the board page
# talks to this socket directly and draws the cursors itself.


class CursorRoom:
    def __init__(self) -> None:
        self.sockets: dict[int, dict[WebSocket, Actor]] = {}

    async def broadcast(self, board_id: int, sender: WebSocket, message: dict) -> None:
        text = json.dumps(message)
        others = [ws for ws in self.sockets.get(board_id, {}) if ws is not sender]
        await asyncio.gather(
            *(ws.send_text(text) for ws in others), return_exceptions=True
        )


room = CursorRoom()
MAX_MESSAGE = 200


@router.websocket("/boards/{board_id}/cursors")
async def cursors(ws: WebSocket, board_id: int, token: str = "") -> None:
    actor = actor_from_socket_token(token, board_id)
    if actor is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    peers = room.sockets.setdefault(board_id, {})
    peers[ws] = actor
    who = {"id": actor.id, "name": actor.name}
    try:
        async for raw in _messages(ws):
            try:
                data = json.loads(raw)
                x, y = float(data["x"]), float(data["y"])
            except (ValueError, KeyError, TypeError):
                continue
            if 0 <= x <= 1 and 0 <= y <= 1:
                await room.broadcast(board_id, ws, {**who, "x": x, "y": y})
    finally:
        peers.pop(ws, None)
        if not peers:
            room.sockets.pop(board_id, None)
        await room.broadcast(board_id, ws, {**who, "gone": True})


async def _messages(ws: WebSocket) -> AsyncIterator[str]:
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) <= MAX_MESSAGE:
                yield raw
    except WebSocketDisconnect:
        return


# --- Wiring ---------------------------------------------------------------


def install(app: FastAPI) -> None:
    app.include_router(router)
    app.include_router(files)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        body: dict = {"detail": exc.message}
        if exc.field:
            body["field"] = exc.field
        return JSONResponse(body, status_code=exc.status_code)
