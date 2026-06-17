"""Factories for building test fixtures.

- :func:`wire_page` — compile an inline ``.wire`` source string into a
  temporary PyWire app for the duration of a ``with`` block.
- :func:`make_principal` — terse constructor for
  :class:`pywire.auth.ClaimsPrincipal` claims in tests.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

from pywire.runtime.app import PyWire
from pywire.runtime.session_store import MemorySessionStore

from pywire.testing.client import TestClient


@contextmanager
def wire_page(
    source: Union[str, dict[str, str]],
    *,
    interactive_server_mode: bool = True,
    route: str = "/",
    **app_kwargs: Any,
) -> Iterator[TestClient]:
    """Yield a :class:`TestClient` for a temporary app built from inline source.

    ``source`` can be a single ``.wire`` source string (mounted at
    ``route``) or a mapping of ``{route: source}`` pairs for multi-page
    apps. Per-test isolation is automatic: a fresh tempdir,
    :class:`MemorySessionStore`, and ``PyWire`` instance are created for
    each invocation and torn down on exit.

    Example::

        with wire_page("---\\n@click\\nasync def inc():\\n    n.value += 1\\n"
                       "---\\n<h1>{n}</h1>") as client:
            response = client.get("/")
            assert response.status_code == 200
    """
    test_dir = tempfile.mkdtemp(prefix="pywire-test-")
    try:
        pages_dir = Path(test_dir) / "pages"
        pages_dir.mkdir()

        if isinstance(source, str):
            sources = {route: source}
        else:
            sources = dict(source)

        for path, src in sources.items():
            filename = _path_to_filename(path)
            target = pages_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(src)

        app = PyWire(
            pages_dir=str(pages_dir),
            interactive_server_mode=interactive_server_mode,
            session_store=MemorySessionStore(),
            **app_kwargs,
        )
        with TestClient(app) as client:
            yield client
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def make_principal(
    *,
    name: str = "test-user",
    user_id: str = "test-user-id",
    is_authenticated: bool = True,
    claims: Optional[Sequence[Union[tuple[str, Any], Any]]] = None,
) -> Any:
    """Build a :class:`pywire.auth.ClaimsPrincipal` for tests.

    ``claims`` accepts ``(type, value)`` tuples or pre-built ``Claim``
    objects. Returns an authenticated principal by default — pass
    ``is_authenticated=False`` for an explicit anonymous user.

    Example::

        admin = make_principal(name="alice", claims=[("role", "admin")])
        client.force_login(admin)
    """
    from pywire.auth import Claim, ClaimsPrincipal

    built: list[Any] = []
    for entry in claims or ():
        if isinstance(entry, Claim):
            built.append(entry)
        else:
            ctype, cvalue = entry
            built.append(Claim(ctype, cvalue))

    return ClaimsPrincipal(
        is_authenticated=is_authenticated,
        name=name,
        user_id=user_id,
        claims=built,
    )


def _path_to_filename(path: str) -> str:
    """Translate a URL route to the .wire filename PyWire's loader expects.

    ``/`` → ``index.wire``; ``/foo/bar`` → ``foo/bar.wire``. Trailing or
    leading slashes are normalised away.
    """
    cleaned = path.strip("/")
    if not cleaned:
        return "index.wire"
    return f"{cleaned}.wire"
