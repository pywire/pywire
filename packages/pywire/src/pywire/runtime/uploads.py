"""Uploaded files: the ``Upload`` a handler receives, and where it waits.

A file reaches the server one of two ways. With JavaScript, the client
sends it to ``/_pywire/upload`` as soon as it is picked and the submit
carries its id; a native form POST carries the file itself. Either way it is
staged in the app's upload store (``PyWire(upload_store=...)``) and the
handler gets an :class:`Upload` to read or ``save()`` somewhere permanent.
Staged files expire (an hour by default), so a handler keeps what it needs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import time
from pathlib import Path
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Dict,
    List,
    Mapping,
    Optional,
    Set,
    Union,
)

from pywire.storage import FileStore, LocalStore, check_key

logger = logging.getLogger(__name__)

PREFIX = "pywire-uploads/"
# Upload references one event may carry; the rest are dropped.
MAX_REFS = 100

_ID = re.compile(r"[0-9a-f]{8,12}-[0-9a-f]{32}")
_EXT = re.compile(r"\.[A-Za-z0-9]{1,10}")
# Types a browser renders or runs when a store serves them.
_ACTIVE_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
        "text/javascript",
        "application/javascript",
    }
)


class Upload:
    """A file sent with a form.

    ``filename`` and ``content_type`` are what the browser said, so treat
    them as hints; ``size`` is counted from the bytes the server received.
    """

    __slots__ = ("filename", "content_type", "size", "_store", "_key")

    def __init__(
        self,
        filename: str,
        content_type: str,
        size: int,
        store: FileStore,
        key: str,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = size
        self._store = store
        self._key = key

    def __repr__(self) -> str:
        return (
            f"<Upload {self.filename!r} {self.content_type} {format_size(self.size)}>"
        )

    @property
    def extension(self) -> str:
        """The filename's extension, lowercased (``".png"``), or ``""``."""
        ext = os.path.splitext(self.filename)[1]
        return ext.lower() if _EXT.fullmatch(ext) else ""

    def _stored_extension(self) -> str:
        """The extension a random key gets: the filename's, unless it names a
        type browsers run (a page, SVG, a script) and the file was declared
        as something else. ``evil.html`` sent as ``image/png`` (which passes
        ``accept="image/*"``) is kept as ``.png``, so a store served to
        browsers never serves it as a page."""
        ext = self.extension
        named = mimetypes.guess_type("x" + ext)[0] if ext else None
        declared = self.content_type.split(";", 1)[0].strip().lower()
        if named not in _ACTIVE_TYPES or named == declared:
            return ext
        guessed = mimetypes.guess_extension(declared) if declared else None
        return guessed if guessed and _EXT.fullmatch(guessed) else ""

    async def read(self) -> bytes:
        """The whole file."""
        return await self._store.get(self._key)

    async def stream(self) -> AsyncIterator[bytes]:
        """The file in chunks, for large files."""
        async for chunk in self._store.stream(self._key):
            yield chunk

    async def save(
        self,
        to: Union[FileStore, str, Path],
        key: Optional[str] = None,
    ) -> str:
        """Keep the file: in a store (returns the key) or at a path.

        ``await upload.save(store)`` picks a random key with the file's
        extension; pass ``key`` to choose it. ``await upload.save("a/b.png")``
        writes a file on disk. The browser's filename is never used as a key
        or path.
        """
        if isinstance(to, (str, Path)):
            if key is not None:
                raise TypeError("save(path) takes no key; the path is the name")
            path = Path(to)
            await LocalStore(path.parent).put(path.name, self.stream())
            return str(path)
        name = check_key(key) if key is not None else secrets.token_hex(16)
        if key is None:
            name += self._stored_extension()
        await to.put(name, self.stream(), content_type=self.content_type)
        return name

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        # Only the server builds Uploads (from a staged file), so validation
        # is an instance check: nothing a client sends as data becomes a file.
        return core_schema.is_instance_schema(cls)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        return {"type": "string", "format": "binary"}


_UNITS = {
    "": 1,
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
}
_SIZE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([a-z]*)\s*", re.IGNORECASE)


def parse_size(size: Union[int, str]) -> int:
    """``2_000_000``, ``"2 MB"`` or ``"1.5 MiB"`` as bytes (KB = 1000, KiB = 1024)."""
    if isinstance(size, bool):
        raise ValueError(f"Invalid size {size!r}")
    if isinstance(size, int):
        if size < 0:
            raise ValueError(f"Invalid size {size!r}")
        return size
    match = _SIZE.fullmatch(size) if isinstance(size, str) else None
    unit = _UNITS.get(match.group(2).lower()) if match else None
    if match is None or unit is None:
        raise ValueError(
            f"Invalid size {size!r}: use bytes or a string like '2 MB' or '512 KiB'"
        )
    return int(float(match.group(1)) * unit)


def format_size(size: int) -> str:
    """Bytes for people: ``2 MiB`` when it divides evenly, else ``2.1 MB``.

    The client formats sizes the same way (``uploads.ts``).
    """
    for unit, factor in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if size >= factor and size % factor == 0:
            return f"{size // factor} {unit}"
    for unit, factor in (("GB", 1000**3), ("MB", 1000**2), ("KB", 1000)):
        if size >= factor:
            text = f"{size / factor:.1f}".removesuffix(".0")
            return f"{text} {unit}"
    return f"{size} B"


def runtime_parent() -> str:
    """One runtime folder per user, so users never share one in /tmp."""
    getuid = getattr(os, "getuid", None)
    return f"pywire_runtime-{getuid()}" if getuid is not None else "pywire_runtime"


def private_dir(path: Path) -> Path:
    """``path``, created readable by this user only (staged uploads and
    upload tokens live in it). Refuses a folder someone else made first."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = path.resolve()
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        for folder in (path.parent, path):
            info = folder.stat()
            if info.st_uid != getuid():
                raise RuntimeError(
                    f"PyWire: {folder} belongs to another user; remove it or "
                    "set TMPDIR to a private folder."
                )
            if info.st_mode & 0o077:
                folder.chmod(0o700)
    return path


def machine_key(path: Path) -> bytes:
    """A random 32-byte key kept at ``path`` (in a private folder), created
    by whichever process asks first, so processes on one machine share it.

    The key is written to a temp file and linked into place, so the file
    appears whole or not at all. Where ``os.link`` doesn't exist (Pyodide,
    which is a single process) it is created exclusively instead. Falls back
    to a key for this process alone when the file can't be used (a read-only
    or missing filesystem) with a warning.
    """
    for attempt in range(50):
        try:
            key = path.read_bytes()
        except FileNotFoundError:
            key = b""
        except OSError:
            break
        if len(key) == 32:
            return key
        if key:
            # Not something this code writes: repair it, then read what won.
            if attempt < 2:
                time.sleep(0.01)
                continue
            temp = path.with_name(f"{path.name}.{secrets.token_hex(8)}")
            try:
                temp.write_bytes(secrets.token_bytes(32))
                temp.chmod(0o600)
                os.replace(temp, path)
            except OSError:
                temp.unlink(missing_ok=True)
                break
            time.sleep(0.05)
            continue
        try:
            if hasattr(os, "link"):
                temp = path.with_name(f"{path.name}.{secrets.token_hex(8)}")
                try:
                    temp.write_bytes(secrets.token_bytes(32))
                    temp.chmod(0o600)
                    os.link(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
            else:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.write(fd, secrets.token_bytes(32))
                finally:
                    os.close(fd)
        except FileExistsError:
            continue
        except OSError:
            break
    global _process_key
    if _process_key is None:
        logger.warning(
            "PyWire: can't keep the upload token key at %s; upload tokens are "
            "only accepted by this process. Set PyWire(secret_key=...) to "
            "share them.",
            path,
        )
        _process_key = secrets.token_bytes(32)
    return _process_key


_process_key: Optional[bytes] = None


class _TooLarge(Exception):
    pass


class Staging:
    """Uploads waiting for a handler, in one store.

    Every staged file has a sidecar ``<id>.json`` with its name, type and
    size, so any process that shares the store can resolve its id.
    """

    def __init__(self, store: FileStore, *, ttl: float = 3600.0) -> None:
        self.store = store
        self.ttl = ttl
        self._last_cleanup = 0.0
        self._tasks: Set[asyncio.Task[Any]] = set()

    async def stage(
        self,
        chunks: AsyncIterable[bytes],
        *,
        filename: str,
        content_type: str,
        limit: int,
        owner: Optional[str] = None,
    ) -> Optional[str]:
        """Store one file; its id, or None when it is larger than ``limit``.

        ``owner`` is the upload token of the page that sent it: a reference
        to the file then resolves only when it carries the same token.
        """
        self._cleanup_soon()
        upload_id = f"{int(time.time()):x}-{secrets.token_hex(16)}"
        key = PREFIX + upload_id
        size = 0

        async def counted() -> AsyncIterator[bytes]:
            nonlocal size
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise _TooLarge
                yield chunk

        try:
            await self.store.put(key, counted(), content_type=content_type)
        except Exception:
            await self.store.delete(key)
            if size > limit:
                return None
            raise
        meta: Dict[str, Any] = {
            "filename": filename,
            "content_type": content_type,
            "size": size,
        }
        if owner is not None:
            meta["owner"] = _owner_hash(owner)
        await self.store.put(
            key + ".json", json.dumps(meta).encode(), content_type="application/json"
        )
        return upload_id

    async def get(
        self, upload_id: object, token: object = None, *, trusted: bool = False
    ) -> Optional[Upload]:
        """The staged file, or None for an unknown, malformed or expired id.

        A file uploaded with a page's token needs that token too, unless the
        id is ``trusted`` (it came from state the server signed).
        """
        if not isinstance(upload_id, str) or not _ID.fullmatch(upload_id):
            return None
        if int(upload_id.split("-", 1)[0], 16) + self.ttl < time.time():
            return None
        key = PREFIX + upload_id
        try:
            meta = json.loads(await self.store.get(key + ".json"))
        except (FileNotFoundError, ValueError):
            return None
        if not isinstance(meta, dict):
            return None
        filename = meta.get("filename")
        content_type = meta.get("content_type")
        size = meta.get("size")
        if not (
            isinstance(filename, str)
            and isinstance(content_type, str)
            and isinstance(size, int)
        ):
            return None
        owner = meta.get("owner")
        if owner is not None and not trusted:
            if not isinstance(token, str) or not hmac.compare_digest(
                str(owner), _owner_hash(token)
            ):
                return None
        return Upload(filename, content_type, size, self.store, key)

    async def discard(self, upload_ids: List[str]) -> None:
        """Delete staged files no handler will get (the request failed)."""
        for upload_id in upload_ids:
            if _ID.fullmatch(upload_id):
                await self.store.delete(PREFIX + upload_id)
                await self.store.delete(PREFIX + upload_id + ".json")

    async def cleanup(self) -> int:
        """Delete expired files; how many were removed."""
        cutoff = time.time() - self.ttl
        removed = 0
        async for key in self.store.list(PREFIX):
            name = key[len(PREFIX) :].removesuffix(".json")
            if not _ID.fullmatch(name):
                continue
            if int(name.split("-", 1)[0], 16) < cutoff:
                await self.store.delete(key)
                removed += 1
        return removed

    def _cleanup_soon(self) -> None:
        now = time.time()
        if now - self._last_cleanup < min(600.0, self.ttl):
            return
        self._last_cleanup = now

        async def run() -> None:
            try:
                await self.cleanup()
            except Exception as exc:
                logger.warning("Cleaning up staged uploads failed: %s", exc)

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def part_chunks(part: Any) -> AsyncIterator[bytes]:
    """A multipart file part (Starlette ``UploadFile``) in chunks."""
    while chunk := await part.read(1024 * 1024):
        yield chunk


def _owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ref(value: Any) -> Optional[str]:
    if isinstance(value, Mapping) and set(value) <= {"_upload_id", "_upload_token"}:
        upload_id = value.get("_upload_id")
        if isinstance(upload_id, str):
            return upload_id
    return None


def has_upload_refs(form_data: Mapping[str, Any]) -> bool:
    return any(
        _ref(v) is not None
        for value in form_data.values()
        for v in (value if isinstance(value, list) else [value])
    )


async def resolve_uploads(
    staging: Staging, form_data: Mapping[str, Any], *, trusted: bool = False
) -> Dict[str, Any]:
    """Replace ``{"_upload_id": ..., "_upload_token": ...}`` references in
    submitted data with Uploads.

    Unknown or expired ids, and ids sent without the token of the page that
    uploaded them, are dropped, as if no file had been chosen.
    """
    budget = MAX_REFS
    out: Dict[str, Any] = {}
    for name, value in form_data.items():
        values = value if isinstance(value, list) else [value]
        if not any(_ref(v) is not None for v in values):
            out[name] = value
            continue
        files: List[Upload] = []
        for v in values:
            upload_id = _ref(v)
            if upload_id is None or budget <= 0:
                continue
            budget -= 1
            upload = await staging.get(
                upload_id, v.get("_upload_token"), trusted=trusted
            )
            if upload is not None:
                files.append(upload)
        if isinstance(value, list):
            out[name] = files
        elif files:
            out[name] = files[0]
    return out


_default: Optional[Staging] = None


def staging_for(page: Any) -> Staging:
    """The upload staging of the app serving ``page``."""
    while getattr(page, "_parent_page", None) is not None:
        page = page._parent_page
    try:
        staging = page.request.app.state.pywire.uploads
    except (AttributeError, KeyError):
        staging = None
    if isinstance(staging, Staging):
        return staging
    global _default
    if _default is None:
        import tempfile

        folder = Path(tempfile.gettempdir()) / runtime_parent() / "uploads"
        _default = Staging(LocalStore(private_dir(folder)))
    return _default


__all__ = ["Upload", "Staging", "parse_size", "format_size", "resolve_uploads"]
