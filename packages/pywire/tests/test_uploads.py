"""Uploads: file stores, staging, ``Upload`` and ``UploadField``."""

import asyncio
import time
from pathlib import Path
from typing import Annotated, Optional

import pytest
from pydantic import BaseModel

from pywire import form
from pywire.forms import Upload, UploadField
from pywire.runtime.uploads import (
    PREFIX,
    Staging,
    format_size,
    parse_size,
    resolve_uploads,
)
from pywire.storage import FileStore, LocalStore, MemoryStore, ObjectStore


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


def _stores(tmp_path: Path):
    obstore = pytest.importorskip("obstore.store")
    return [
        LocalStore(tmp_path / "files"),
        MemoryStore(),
        ObjectStore(obstore.MemoryStore()),
    ]


def test_stores_share_one_interface(tmp_path):
    async def run(store: FileStore) -> None:
        assert isinstance(store, FileStore)
        await store.put("a/one.txt", b"hello")
        await store.put("a/two.txt", _chunks(b"wor", b"ld"), content_type="text/plain")
        await store.put("b.txt", bytearray(b"b"))
        assert await store.get("a/one.txt") == b"hello"
        assert b"".join([c async for c in store.stream("a/two.txt")]) == b"world"
        assert await store.exists("a/one.txt")
        assert not await store.exists("a/nope.txt")
        assert [k async for k in store.list("a/")] == ["a/one.txt", "a/two.txt"]
        await store.delete("a/one.txt")
        await store.delete("a/one.txt")  # missing: no error
        with pytest.raises(FileNotFoundError):
            await store.get("a/one.txt")
        with pytest.raises(FileNotFoundError):
            [c async for c in store.stream("a/one.txt")]

    for store in _stores(tmp_path):
        asyncio.run(run(store))


@pytest.mark.parametrize(
    "key", ["", "/abs", "../up", "a/../b", "a//b", "a/./b", "a\\b", "a/", 7]
)
def test_unsafe_keys_are_refused(tmp_path, key):
    async def run(store: FileStore) -> None:
        with pytest.raises(ValueError, match="Invalid storage key"):
            await store.put(key, b"x")
        with pytest.raises(ValueError, match="Invalid storage key"):
            await store.get(key)

    for store in _stores(tmp_path):
        asyncio.run(run(store))


def test_local_store_writes_whole_files_only(tmp_path):
    store = LocalStore(tmp_path)

    async def broken():
        yield b"half"
        raise RuntimeError("client went away")

    async def run() -> None:
        with pytest.raises(RuntimeError):
            await store.put("x.bin", broken())
        assert not await store.exists("x.bin")
        assert [k async for k in store.list()] == []

    asyncio.run(run())
    assert list(tmp_path.iterdir()) == []


def test_object_store_needs_the_extra_only_when_used():
    store = ObjectStore.from_url("memory:///")
    assert "ObjectStore" in repr(store)


def test_sizes():
    assert parse_size(10) == 10
    assert parse_size("2 MB") == 2_000_000
    assert parse_size("2mb") == 2_000_000
    assert parse_size("1.5 KiB") == 1536
    assert parse_size("512KiB") == 512 * 1024
    for bad in ("2 MiBs", "-1", "", "MB", True, -1):
        with pytest.raises(ValueError):
            parse_size(bad)  # type: ignore[arg-type]
    assert format_size(500) == "500 B"
    assert format_size(2_000_000) == "2 MB"
    assert format_size(2_100_000) == "2.1 MB"
    assert format_size(2 * 1024 * 1024) == "2 MiB"
    assert format_size(1536) == "1.5 KB"


def _stage(staging: Staging, body: bytes, limit: int = 1000) -> Optional[str]:
    return asyncio.run(
        staging.stage(
            _chunks(body), filename="a.png", content_type="image/png", limit=limit
        )
    )


def test_staging_round_trip():
    staging = Staging(MemoryStore())
    upload_id = _stage(staging, b"png!")
    assert upload_id is not None
    upload = asyncio.run(staging.get(upload_id))
    assert upload is not None
    assert (upload.filename, upload.content_type, upload.size) == (
        "a.png",
        "image/png",
        4,
    )
    assert asyncio.run(upload.read()) == b"png!"


def test_staging_refuses_files_over_the_limit():
    store = MemoryStore()
    staging = Staging(store)
    assert _stage(staging, b"x" * 11, limit=10) is None

    async def keys():
        return [k async for k in store.list()]

    assert asyncio.run(keys()) == []


@pytest.mark.parametrize(
    "upload_id",
    ["../../etc/passwd", "/etc/passwd", "abc", "", None, "0" * 36, {"x": 1}],
)
def test_staging_ignores_malformed_ids(upload_id):
    assert asyncio.run(Staging(MemoryStore()).get(upload_id)) is None


def _old_file(store: MemoryStore) -> str:
    old_id = f"{int(time.time()) - 120:x}-{'a' * 32}"
    asyncio.run(store.put(PREFIX + old_id, b"old"))
    asyncio.run(store.put(PREFIX + old_id + ".json", b"{}"))
    return old_id


def test_staged_files_expire():
    store = MemoryStore()
    staging = Staging(store, ttl=60)
    old_id = _old_file(store)
    assert asyncio.run(staging.get(old_id)) is None
    assert asyncio.run(staging.cleanup()) == 2
    fresh_id = _stage(staging, b"new")
    assert asyncio.run(staging.get(fresh_id)) is not None
    assert asyncio.run(staging.cleanup()) == 0


def test_staging_cleans_up_as_it_goes():
    store = MemoryStore()
    staging = Staging(store, ttl=60)
    _old_file(store)

    async def run():
        fresh_id = await staging.stage(
            _chunks(b"new"), filename="a", content_type="text/plain", limit=10
        )
        await asyncio.gather(*staging._tasks)
        return fresh_id, [k async for k in store.list()]

    fresh_id, keys = asyncio.run(run())
    assert keys == [PREFIX + fresh_id, PREFIX + fresh_id + ".json"]


def test_resolve_uploads_turns_ids_into_files():
    staging = Staging(MemoryStore())
    one = _stage(staging, b"1")
    two = _stage(staging, b"22")
    data = asyncio.run(
        resolve_uploads(
            staging,
            {
                "name": "Al",
                "avatar": {"_upload_id": one},
                "docs": [{"_upload_id": two}, {"_upload_id": "bogus"}],
                "gone": {"_upload_id": "bogus"},
            },
        )
    )
    assert data["name"] == "Al"
    assert isinstance(data["avatar"], Upload) and data["avatar"].size == 1
    assert [d.size for d in data["docs"]] == [2]
    assert "gone" not in data


def test_upload_save(tmp_path):
    staging = Staging(MemoryStore())
    upload = asyncio.run(staging.get(_stage(staging, b"img")))
    assert upload is not None and upload.extension == ".png"
    kept = LocalStore(tmp_path / "kept")

    key = asyncio.run(upload.save(kept))
    assert key.endswith(".png") and len(key) == 36
    assert asyncio.run(kept.get(key)) == b"img"
    assert asyncio.run(upload.save(kept, "avatars/1.png")) == "avatars/1.png"
    with pytest.raises(ValueError):
        asyncio.run(upload.save(kept, "../escape.png"))

    path = tmp_path / "disk" / "a.png"
    assert asyncio.run(upload.save(path)) == str(path)
    assert path.read_bytes() == b"img"
    with pytest.raises(TypeError):
        asyncio.run(upload.save(path, "key"))


def test_upload_extension_never_trusts_odd_names():
    store = MemoryStore()
    assert Upload("../../x.PNG", "", 0, store, "k").extension == ".png"
    assert Upload("x.tar.gz", "", 0, store, "k").extension == ".gz"
    assert Upload("x.<script>", "", 0, store, "k").extension == ""
    assert Upload("noext", "", 0, store, "k").extension == ""


class Profile(BaseModel):
    avatar: Annotated[Upload, UploadField(max_size="1 KB", accept="image/*,.svg")]
    papers: Annotated[
        list[Upload], UploadField(max_files=2, accept=["application/pdf"])
    ] = []


def _upload(name: str, ctype: str, size: int) -> Upload:
    return Upload(name, ctype, size, MemoryStore(), "k")


def _errors(**files):
    f = form(Profile)
    got = []

    async def run():
        await f._pw_submit(None, got.append, {"type": "submit", "formData": files})

    asyncio.run(run())
    return f.errors, got


def test_upload_field_checks_size_type_and_count():
    ok = _upload("a.png", "image/png", 1000)
    errors, got = _errors(avatar=ok, papers=[_upload("p.pdf", "application/pdf", 5)])
    assert errors == {} and got[0].avatar is ok

    errors, _ = _errors(avatar=_upload("a.png", "image/png", 1001))
    assert errors == {"avatar": "Choose a file no larger than 1 KB"}

    errors, _ = _errors(avatar=_upload("a.txt", "text/plain", 1))
    assert errors == {"avatar": "Choose a file of type image/*, .svg"}

    errors, _ = _errors(avatar=_upload("logo.SVG", "application/octet-stream", 1))
    assert errors == {}

    pdf = _upload("p.pdf", "application/pdf; charset=binary", 1)
    errors, _ = _errors(avatar=ok, papers=[pdf, pdf, pdf])
    assert errors == {"papers": "Choose at most 2 files"}

    errors, _ = _errors(avatar=ok, papers=[pdf, _upload("p.doc", "text/x", 1)])
    assert errors == {"papers": "Choose a file of type application/pdf"}


def test_upload_field_error_codes():
    f = form(Profile)
    asyncio.run(
        f._pw_submit(
            None,
            None,
            {"type": "submit", "formData": {"avatar": _upload("a", "image/png", 5000)}},
        )
    )
    assert f.avatar.errors[0].code == "fileTooLarge"


def test_upload_field_rejects_bad_rules():
    with pytest.raises(ValueError):
        UploadField(max_files=0)
    with pytest.raises(ValueError):
        UploadField(max_size="lots")
