"""Pin stateless ``{$await}`` hold-open and cancellation semantics.

Review Focus #4: an overlong await must not hold the response open past
``await_budget`` — the handler returns ≈ budget after the handler returns,
unfinished tasks are cancelled and counted in ``meta.pending_awaits``, and a
cancelled task never writes to the (already closed) response. A fast await
resolves in band with ``pending_awaits == 0``.
"""

import time
from pathlib import Path

import msgpack
import pytest
from starlette.testclient import TestClient

from pywire.runtime.app import PyWire

FIXTURE_PAGES = Path(__file__).parent / "fixtures" / "stateless_app" / "pages"
SECRET = "test-secret-key"

_MSGPACK = {"Content-Type": "application/x-msgpack"}


@pytest.fixture()
def client_await_budget():
    app = PyWire(
        pages_dir=str(FIXTURE_PAGES),
        stateless=True,
        secret_key=SECRET,
        await_budget=0.3,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _blob(html: str) -> str:
    return html.split('_pywire_snapshot" type="text/plain">')[1].split("</script>")[0]


def _post(client, path, blob, handler=None):
    return client.post(
        "/_pywire/stateless",
        content=msgpack.packb(
            {"path": path, "handler": handler, "data": {}, "snapshot": blob}
        ),
        headers=_MSGPACK,
    )


def test_overlong_await_returns_at_budget(client_await_budget):
    blob = _blob(client_await_budget.get("/slow").text)
    t0 = time.perf_counter()
    r = _post(client_await_budget, "/slow", blob)
    dt = time.perf_counter() - t0
    assert r.status_code == 200
    # budget is 0.3 s; 2.0 is a generous upper bound that guards CI flakiness
    # while still proving the 10 s await did not hold the response open.
    assert dt < 2.0
    assert msgpack.unpackb(r.content, raw=False)["meta"]["pending_awaits"] == 1


def test_fast_await_resolves_in_band(client_await_budget):
    blob = _blob(client_await_budget.get("/fast").text)
    r = _post(client_await_budget, "/fast", blob)
    assert r.status_code == 200
    msg = msgpack.unpackb(r.content, raw=False)
    assert msg["meta"]["pending_awaits"] == 0