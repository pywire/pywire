"""Where files live: one interface over disk, memory and object stores.

    from pywire.storage import LocalStore

    avatars = LocalStore("var/avatars")

    async def save(profile: Profile):
        key = await profile.avatar.save(avatars)

Every store speaks :class:`FileStore`, so swapping ``LocalStore`` for
``ObjectStore.from_url("s3://bucket/avatars")`` (S3, R2, GCS or Azure, with
``pip install "pywire[storage]"``) changes nothing else. PyWire stages
uploads in one as well: ``PyWire(upload_store=...)``.

Keys are ``/``-separated names such as ``"avatars/42.png"``: no leading
``/``, no empty, ``.`` or ``..`` segments, no backslashes. Reading a key
that isn't there raises ``FileNotFoundError``; deleting one is a no-op.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    BinaryIO,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

Data = Union[bytes, bytearray, memoryview, AsyncIterable[bytes]]

CHUNK_SIZE = 1024 * 1024
_TMP = ".pw-tmp-"


@runtime_checkable
class FileStore(Protocol):
    """A place to put files by key."""

    async def put(
        self, key: str, data: Data, *, content_type: Optional[str] = None
    ) -> None:
        """Write ``data`` (bytes or an async iterable of chunks) at ``key``."""
        ...

    async def get(self, key: str) -> bytes:
        """The whole file. Raises ``FileNotFoundError``."""
        ...

    def stream(self, key: str) -> AsyncIterator[bytes]:
        """The file in chunks. Raises ``FileNotFoundError``."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None:
        """Remove the file; no error when it isn't there."""
        ...

    def list(self, prefix: str = "") -> AsyncIterator[str]:
        """Every key under ``prefix``, a folder such as ``"avatars/"``."""
        ...


def check_key(key: object) -> str:
    """``key`` when it is a safe store key; else ``ValueError``."""
    if not isinstance(key, str) or not key or len(key) > 1024:
        raise ValueError(f"Invalid storage key {key!r}")
    if key.startswith("/") or "\\" in key or "\0" in key:
        raise ValueError(f"Invalid storage key {key!r}")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise ValueError(f"Invalid storage key {key!r}")
    return key


async def _chunks(data: Data) -> AsyncIterator[bytes]:
    if isinstance(data, (bytes, bytearray, memoryview)):
        yield bytes(data)
        return
    async for chunk in data:
        yield bytes(chunk)


def _reader(path: Path) -> BinaryIO:
    return open(path, "rb")


def _writer(path: Path) -> BinaryIO:
    return open(path, "wb")


class LocalStore:
    """Files in a directory on this machine."""

    def __init__(self, root: Union[str, "os.PathLike[str]"]) -> None:
        self.root = Path(root).resolve()

    def __repr__(self) -> str:
        return f"LocalStore({str(self.root)!r})"

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*check_key(key).split("/"))

    async def put(
        self, key: str, data: Data, *, content_type: Optional[str] = None
    ) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        # Write beside the target, then rename: readers never see half a file.
        tmp = path.with_name(f"{_TMP}{secrets.token_hex(8)}")
        try:
            handle = await asyncio.to_thread(_writer, tmp)
            try:
                async for chunk in _chunks(data):
                    await asyncio.to_thread(handle.write, chunk)
            finally:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(os.replace, tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        handle = await asyncio.to_thread(_reader, self._path(key))
        try:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_SIZE):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        def walk() -> List[str]:
            keys = []
            for folder, _, names in os.walk(self.root):
                rel = Path(folder).relative_to(self.root).as_posix()
                base = "" if rel == "." else rel + "/"
                keys.extend(
                    base + name
                    for name in names
                    if not name.startswith(_TMP) and (base + name).startswith(prefix)
                )
            return sorted(keys)

        for key in await asyncio.to_thread(walk):
            yield key


class MemoryStore:
    """Files in this process's memory: tests, and single-process dev servers."""

    def __init__(self) -> None:
        self._files: Dict[str, bytes] = {}

    def __repr__(self) -> str:
        return f"MemoryStore({len(self._files)} files)"

    async def put(
        self, key: str, data: Data, *, content_type: Optional[str] = None
    ) -> None:
        check_key(key)
        self._files[key] = b"".join([chunk async for chunk in _chunks(data)])

    async def get(self, key: str) -> bytes:
        try:
            return self._files[check_key(key)]
        except KeyError:
            raise FileNotFoundError(key) from None

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        content = await self.get(key)
        for start in range(0, len(content), CHUNK_SIZE):
            yield content[start : start + CHUNK_SIZE]

    async def exists(self, key: str) -> bool:
        return check_key(key) in self._files

    async def delete(self, key: str) -> None:
        self._files.pop(check_key(key), None)

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        for key in sorted(k for k in self._files if k.startswith(prefix)):
            yield key


class ObjectStore:
    """S3, R2, Google Cloud Storage or Azure Blob Storage, through obstore.

    Needs ``pip install "pywire[storage]"``. Build one from a URL, with the
    provider's options as keywords::

        ObjectStore.from_url("s3://bucket/uploads", region="us-east-1")
        ObjectStore.from_url(
            "s3://bucket", endpoint="https://<account>.r2.cloudflarestorage.com"
        )
        ObjectStore.from_url("gs://bucket/uploads")
        ObjectStore.from_url("az://container/uploads", account_name="...")

    Credentials not passed come from the provider's usual environment
    variables. Or wrap a store you built with ``obstore.store`` yourself:
    ``ObjectStore(S3Store(...))``.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def __repr__(self) -> str:
        return f"ObjectStore({self.store!r})"

    @classmethod
    def from_url(cls, url: str, **options: Any) -> "ObjectStore":
        return cls(_obstore().store.from_url(url, **options))

    async def put(
        self, key: str, data: Data, *, content_type: Optional[str] = None
    ) -> None:
        payload: Any = (
            bytes(data) if isinstance(data, (bytearray, memoryview)) else data
        )
        await _obstore().put_async(
            self.store,
            check_key(key),
            payload,
            attributes={"Content-Type": content_type} if content_type else None,
        )

    async def get(self, key: str) -> bytes:
        result = await _obstore().get_async(self.store, check_key(key))
        return bytes(await result.bytes_async())

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        result = await _obstore().get_async(self.store, check_key(key))
        async for chunk in result.stream(min_chunk_size=CHUNK_SIZE):
            yield bytes(chunk)

    async def exists(self, key: str) -> bool:
        try:
            await _obstore().head_async(self.store, check_key(key))
        except FileNotFoundError:
            return False
        return True

    async def delete(self, key: str) -> None:
        try:
            await _obstore().delete_async(self.store, check_key(key))
        except FileNotFoundError:
            pass

    async def list(self, prefix: str = "") -> AsyncIterator[str]:
        async for batch in _obstore().list(self.store, prefix=prefix or None):
            for meta in batch:
                yield str(meta["path"])


def _obstore() -> Any:
    try:
        import obstore
        import obstore.store  # noqa: F401
    except ImportError:
        raise ImportError(
            'ObjectStore needs obstore: pip install "pywire[storage]"'
        ) from None
    return obstore


__all__ = ["FileStore", "LocalStore", "MemoryStore", "ObjectStore", "check_key"]
