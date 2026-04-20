"""In-memory AuthStore.

Suitable for single-worker development. Data is lost on process
restart; for production use a persistent store (e.g.,
``SQLAlchemyAuthStore``).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple


class MemoryAuthStore:
    def __init__(self) -> None:
        self._users: Dict[str, Dict[str, Any]] = {}
        self._pw_hashes: Dict[str, str] = {}
        # (provider, subject) -> user_id
        self._identities: Dict[Tuple[str, str], str] = {}

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._users.get(user_id)

    async def find_by_provider(
        self, provider: str, subject: str
    ) -> Optional[Dict[str, Any]]:
        user_id = self._identities.get((provider, subject))
        if user_id is None:
            return None
        return self._users.get(user_id)

    async def create_user(self, **fields: Any) -> str:
        user_id = fields.pop("user_id", None) or str(uuid.uuid4())
        self._users[user_id] = {"user_id": user_id, **fields}
        return user_id

    async def update_user(self, user_id: str, **fields: Any) -> None:
        if user_id not in self._users:
            return
        self._users[user_id].update(fields)

    async def link_provider(
        self,
        user_id: str,
        provider: str,
        subject: str,
        claims: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._identities[(provider, subject)] = user_id
        record = self._users.setdefault(user_id, {"user_id": user_id})
        linked = record.setdefault("linked", {})
        linked[provider] = {"subject": subject, "claims": claims or {}}

    async def get_password_hash(self, user_id: str) -> Optional[str]:
        return self._pw_hashes.get(user_id)

    async def set_password_hash(self, user_id: str, hash: str) -> None:
        self._pw_hashes[user_id] = hash
