"""SQLAlchemy-backed AuthStore.

Persists users, password hashes, and OIDC/local provider links across
process restarts. Uses the async SQLAlchemy engine — works with SQLite
(dev), Postgres, MySQL, any async-compatible backend.

Smallest-viable-schema: three tables (``users``, ``credentials``,
``provider_links``) with JSON columns for claims and extras. No
migrations shipped; apps that need Alembic wire it themselves against
this module's :data:`metadata`.

Example::

    from pywire_auth.stores import SQLAlchemyAuthStore

    store = SQLAlchemyAuthStore("sqlite+aiosqlite:///./pywire-auth.db")
    await store.init_schema()  # one-time; creates tables if missing
    idp = LocalIdP(store=store, secret=...)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

try:
    from sqlalchemy import JSON, Column, String, Table, select
    from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
    from sqlalchemy.sql.schema import MetaData
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "SQLAlchemyAuthStore requires the sqlalchemy extra: "
        "pip install 'pywire-auth[sqlalchemy]'"
    ) from exc


metadata = MetaData()


users_table = Table(
    "pywire_auth_users",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("email", String, index=True),
    Column("name", String, default=""),
    Column("claims", JSON, default=dict),
    Column("extras", JSON, default=dict),
)

credentials_table = Table(
    "pywire_auth_credentials",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("pw_hash", String),
)

provider_links_table = Table(
    "pywire_auth_provider_links",
    metadata,
    Column("provider", String, primary_key=True),
    Column("subject", String, primary_key=True),
    Column("user_id", String, index=True),
    Column("claims", JSON, default=dict),
)


class SQLAlchemyAuthStore:
    """AuthStore backed by an async SQLAlchemy engine.

    Accepts either a URL string (will construct an async engine) or an
    already-built :class:`AsyncEngine` (for apps that share a single
    engine across stores / app code).
    """

    def __init__(
        self,
        url_or_engine: str | AsyncEngine,
        *,
        auto_init: bool = True,
    ) -> None:
        if isinstance(url_or_engine, str):
            self._engine: AsyncEngine = create_async_engine(url_or_engine)
            self._owns_engine = True
        else:
            self._engine = url_or_engine
            self._owns_engine = False
        self._schema_ready = not auto_init
        self._init_lock: Optional[Any] = None

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def init_schema(self) -> None:
        """Create the three tables if they don't already exist. Idempotent."""
        async with self._engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        self._schema_ready = True

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        import asyncio

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._schema_ready:
                return
            await self.init_schema()

    async def close(self) -> None:
        """Dispose the engine (only if we created it)."""
        if self._owns_engine:
            await self._engine.dispose()

    # --- AuthStore protocol ---

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(users_table).where(users_table.c.user_id == user_id)
                )
            ).first()
            if row is None:
                return None
            record = self._row_to_user(row)
            # Pull linked providers so the record mirrors MemoryAuthStore shape.
            links = (
                await conn.execute(
                    select(provider_links_table).where(
                        provider_links_table.c.user_id == user_id
                    )
                )
            ).all()
            linked: Dict[str, Dict[str, Any]] = {}
            for link in links:
                linked[link.provider] = {
                    "subject": link.subject,
                    "claims": _as_dict(link.claims),
                }
            if linked:
                record["linked"] = linked
            return record

    async def find_by_provider(
        self, provider: str, subject: str
    ) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            link = (
                await conn.execute(
                    select(provider_links_table).where(
                        provider_links_table.c.provider == provider,
                        provider_links_table.c.subject == subject,
                    )
                )
            ).first()
            if link is None:
                return None
            return await self.get_user(link.user_id)

    async def create_user(self, **fields: Any) -> str:
        await self._ensure_schema()
        user_id = fields.pop("user_id", None) or str(uuid.uuid4())
        email = fields.pop("email", None)
        name = fields.pop("name", "") or ""
        claims = fields.pop("claims", {}) or {}
        # Anything else lands in extras — preserves forward-compat with
        # extra kwargs LocalIdP.create_user may pass through.
        extras = fields
        async with self._engine.begin() as conn:
            await conn.execute(
                users_table.insert().values(
                    user_id=user_id,
                    email=email,
                    name=name,
                    claims=claims,
                    extras=extras,
                )
            )
        return user_id

    async def update_user(self, user_id: str, **fields: Any) -> None:
        if not fields:
            return
        await self._ensure_schema()
        # Separate known columns from extras.
        known = {
            k: v for k, v in fields.items() if k in ("email", "name", "claims")
        }
        extra_updates = {
            k: v for k, v in fields.items() if k not in known
        }
        async with self._engine.begin() as conn:
            if known:
                await conn.execute(
                    users_table.update()
                    .where(users_table.c.user_id == user_id)
                    .values(**known)
                )
            if extra_updates:
                # Merge into existing extras JSON.
                row = (
                    await conn.execute(
                        select(users_table.c.extras).where(
                            users_table.c.user_id == user_id
                        )
                    )
                ).first()
                if row is not None:
                    merged = _as_dict(row.extras)
                    merged.update(extra_updates)
                    await conn.execute(
                        users_table.update()
                        .where(users_table.c.user_id == user_id)
                        .values(extras=merged)
                    )

    async def link_provider(
        self,
        user_id: str,
        provider: str,
        subject: str,
        claims: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(provider_links_table).where(
                        provider_links_table.c.provider == provider,
                        provider_links_table.c.subject == subject,
                    )
                )
            ).first()
            if existing is None:
                await conn.execute(
                    provider_links_table.insert().values(
                        provider=provider,
                        subject=subject,
                        user_id=user_id,
                        claims=claims or {},
                    )
                )
            else:
                await conn.execute(
                    provider_links_table.update()
                    .where(
                        provider_links_table.c.provider == provider,
                        provider_links_table.c.subject == subject,
                    )
                    .values(user_id=user_id, claims=claims or {})
                )

    async def get_password_hash(self, user_id: str) -> Optional[str]:
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(credentials_table.c.pw_hash).where(
                        credentials_table.c.user_id == user_id
                    )
                )
            ).first()
            return row.pw_hash if row is not None else None

    async def set_password_hash(self, user_id: str, hash: str) -> None:
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(credentials_table.c.user_id).where(
                        credentials_table.c.user_id == user_id
                    )
                )
            ).first()
            if existing is None:
                await conn.execute(
                    credentials_table.insert().values(
                        user_id=user_id, pw_hash=hash
                    )
                )
            else:
                await conn.execute(
                    credentials_table.update()
                    .where(credentials_table.c.user_id == user_id)
                    .values(pw_hash=hash)
                )

    # --- helpers ---

    @staticmethod
    def _row_to_user(row: Any) -> Dict[str, Any]:
        record = {
            "user_id": row.user_id,
            "email": row.email,
            "name": row.name,
            "claims": _as_dict(row.claims),
        }
        extras = _as_dict(row.extras)
        if extras:
            record.update(extras)
        return record


def _as_dict(value: Any) -> Dict[str, Any]:
    """JSON columns sometimes come back as strings on SQLite — normalize."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
