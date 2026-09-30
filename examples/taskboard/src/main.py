"""Compose the app: FastAPI in front, pywire mounted at /, one lifespan.

Run it with ``uv run pywire dev src.main:app`` (development) or
``uv run pywire run src.main:app --workers 1`` (production; see the README
about workers). Both serve this FastAPI ``app``, not the PyWire one.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pywire_auth import connect_auth

from pywire import PyWire
from taskboard import api, db
from taskboard.identity import idp, store
from taskboard.settings import settings

ui = PyWire(pages_dir="src/pages", fallthrough_404=True)

# Session cookies, /auth/local/{login,register,revoke}, and self.user on pages.
connect_auth(
    ui, local_idp=idp, secret_key=settings.session_secret, default_next="/boards"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.create_tables()
    # A host app doesn't run the lifespan of apps mounted in it, so enter
    # pywire's here (session store connect, flush on shutdown).
    async with ui.lifespan():
        yield
    await store.close()
    await db.engine.dispose()


app = FastAPI(title="Taskboard", lifespan=lifespan)
api.install(app)

# Last, so /api/* and /files/* match first and everything else falls through
# to pywire. Passing the host makes pywire's SPA navigations run through
# FastAPI's middleware too.
app.mount("/", ui.as_asgi(app))
