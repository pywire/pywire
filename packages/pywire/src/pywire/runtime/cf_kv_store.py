"""Cloudflare Workers KV session store for PyWire.

Uses the Cloudflare Workers KV binding via Pyodide's FFI bridge.
In Python Workers, `env.KV_NAMESPACE` is a JsProxy that exposes
async `.get()`, `.put()`, `.delete()`, and `.list()` methods.

This store requires no additional dependencies — it uses the KV
binding directly from the Workers runtime environment.

See: https://developers.cloudflare.com/workers/languages/python/ffi/
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CloudflareKVSessionStore:
    """Cloudflare Workers KV session store.

    Args:
        kv_binding: The KV namespace binding from ``env`` (a JsProxy object).
            Typically ``env.PYWIRE_SESSIONS`` or similar.
        prefix: Key prefix for session data in KV.
    """

    def __init__(self, kv_binding: Any, prefix: str = "pywire:session:") -> None:
        self._kv = kv_binding
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._kv.get(self._key(session_id))
        if raw is None:
            return None
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        # Check TTL expiration
        expires_at = envelope.get("expires_at")
        if expires_at is not None and time.time() > expires_at:
            # Expired — clean up asynchronously
            await self.delete(session_id)
            return None

        # Touch TTL on read so active sessions don't expire
        ttl = envelope.get("ttl")
        if ttl is not None:
            envelope["expires_at"] = time.time() + ttl
            await self._kv.put(
                self._key(session_id),
                json.dumps(envelope),
                # KV's built-in expiration as a safety net (add buffer for touch-on-read)
                expirationTtl=ttl + 300,
            )

        return envelope.get("data")

    async def set(
        self, session_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        envelope: Dict[str, Any] = {"data": data}
        kv_opts: Dict[str, Any] = {}

        if ttl is not None:
            envelope["ttl"] = ttl
            envelope["expires_at"] = time.time() + ttl
            # KV native expiration as a safety net (with buffer for touch-on-read)
            kv_opts["expirationTtl"] = ttl + 300

        await self._kv.put(
            self._key(session_id),
            json.dumps(envelope),
            **kv_opts,
        )

    async def delete(self, session_id: str) -> None:
        await self._kv.delete(self._key(session_id))

    async def exists(self, session_id: str) -> bool:
        raw = await self._kv.get(self._key(session_id))
        if raw is None:
            return False
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return False
        expires_at = envelope.get("expires_at")
        if expires_at is not None and time.time() > expires_at:
            return False
        return True

    async def touch(self, session_id: str, ttl: Optional[int] = None) -> None:
        raw = await self._kv.get(self._key(session_id))
        if raw is None:
            return
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        if ttl is not None:
            envelope["ttl"] = ttl
            envelope["expires_at"] = time.time() + ttl
            await self._kv.put(
                self._key(session_id),
                json.dumps(envelope),
                expirationTtl=ttl + 300,
            )

    async def close(self) -> None:
        # No cleanup needed — KV bindings are managed by the Workers runtime
        pass
