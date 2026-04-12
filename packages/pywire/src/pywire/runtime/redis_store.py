"""Redis-backed session store for PyWire.

Uses redis.asyncio for async Redis operations. Covers all Redis-compatible
providers: Render KV, Fly Upstash, AWS ElastiCache, GCP Memorystore,
Azure Cache for Redis.

Install: pip install pywire[redis]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import msgpack

logger = logging.getLogger(__name__)

_MISSING_REDIS_MSG = (
    "redis package is required for RedisSessionStore. "
    "Install it with: pip install pywire[redis]"
)


class RedisSessionStore:
    """Redis-backed session store.

    Args:
        url: Redis connection URL (e.g. redis://localhost:6379, rediss://...).
            Typically provided via REDIS_URL environment variable.
        prefix: Key prefix for session data in Redis.
    """

    def __init__(self, url: str, prefix: str = "pywire:session:") -> None:
        self._url = url
        self._prefix = prefix
        self._redis: Any = None
        self._ttl: Dict[str, int] = {}  # session_id -> original TTL in seconds

    async def connect(self) -> None:
        """Initialize the Redis connection pool."""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise ImportError(_MISSING_REDIS_MSG) from None

        self._redis = aioredis.from_url(self._url)
        # Verify connectivity
        await self._redis.ping()
        logger.info("Connected to Redis session store")

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self._redis is None:
            await self.connect()
        key = self._key(session_id)
        data = await self._redis.get(key)
        if data is None:
            return None
        # Touch TTL on read so active sessions don't expire
        original_ttl = self._ttl.get(session_id)
        if original_ttl:
            await self._redis.expire(key, original_ttl)
        return msgpack.unpackb(data, raw=False)

    async def set(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        if self._redis is None:
            await self.connect()
        packed = msgpack.packb(data, use_bin_type=True)
        key = self._key(session_id)
        if ttl:
            await self._redis.setex(key, ttl, packed)
            self._ttl[session_id] = ttl
        else:
            await self._redis.set(key, packed)

    async def delete(self, session_id: str) -> None:
        if self._redis is None:
            await self.connect()
        await self._redis.delete(self._key(session_id))
        self._ttl.pop(session_id, None)

    async def exists(self, session_id: str) -> bool:
        if self._redis is None:
            await self.connect()
        return bool(await self._redis.exists(self._key(session_id)))

    async def touch(self, session_id: str, ttl: Optional[int] = None) -> None:
        if self._redis is None:
            await self.connect()
        if ttl:
            await self._redis.expire(self._key(session_id), ttl)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            self._ttl.clear()
            logger.info("Closed Redis session store connection")
