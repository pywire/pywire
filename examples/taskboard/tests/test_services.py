"""Rules that live only in services."""

import pytest

from pywire.forms import Upload
from pywire.storage import MemoryStore
from taskboard import db, services
from taskboard.errors import Invalid
from taskboard.schemas import ProfileIn

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _upload(content: bytes, name: str = "me.png") -> Upload:
    store = MemoryStore()
    store._files["staged"] = content
    return Upload(name, "image/png", len(content), store, "staged")


def _save(client, actor, data):
    async def run():
        async with db.session() as s:
            return await services.save_profile(s, actor, data)

    return client.portal.call(run)


def test_avatars_are_checked_by_content_not_name(client, make_user):
    ada = make_user("Ada Lovelace")
    with pytest.raises(Invalid) as refused:
        _save(
            client,
            ada.actor,
            ProfileIn(display_name="Ada", avatar=_upload(b"<script>alert(1)</script>")),
        )
    assert refused.value.field == "avatar"

    profile = _save(
        client,
        ada.actor,
        ProfileIn(display_name="Ada", avatar=_upload(PNG, "photo.gif")),
    )
    assert profile.avatar_key.endswith(".png")
    served = client.get(f"/files/avatars/{profile.avatar_key}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


def test_avatar_route_takes_only_generated_keys(client):
    assert client.get("/files/avatars/..%2Fsecrets.png").status_code == 404
    assert client.get("/files/avatars/not-a-key.png").status_code == 404
