"""Every page renders in stateless mode and carries its signed snapshot."""

import os
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

os.environ.setdefault("PYWIRE_SECRET_KEY", "test-only-" + "x" * 32)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="module")
def client():
    from main import app

    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/about", "/poll"])
def test_page_renders_with_a_snapshot(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'id="_pywire_snapshot"' in response.text
