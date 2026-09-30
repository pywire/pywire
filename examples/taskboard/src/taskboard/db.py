"""Database engine and sessions.

One ``AsyncEngine`` for the process, shared with pywire-auth's user store.
Code that needs the database opens a session with ``async with session()``;
a FastAPI route gets one from the ``get_session`` dependency. Either way the
session commits when the block exits cleanly and rolls back on an error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from taskboard.settings import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url)
_sessions = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with _sessions() as s:
        async with s.begin():
            yield s
        # Committed. Now tell everyone else: publishing before the commit
        # would let other pages re-read the database and miss this change.
        for publish in s.info.pop("after_commit", []):
            await publish()


def after_commit(s: AsyncSession, publish: Callable[[], Awaitable[None]]) -> None:
    """Run ``publish`` once this session's transaction has committed."""
    s.info.setdefault("after_commit", []).append(publish)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: ``db: AsyncSession = Depends(get_session)``."""
    async with session() as s:
        yield s


async def create_tables() -> None:
    """Create missing tables. A real app runs Alembic migrations instead."""
    from taskboard import models  # noqa: F401  (registers the tables)

    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        from pathlib import Path

        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
