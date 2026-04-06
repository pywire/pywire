import asyncio
from pathlib import Path

import pytest

_E2E_DIR = Path(__file__).parent / "e2e"


@pytest.fixture(autouse=True)
def _clear_playwright_event_loop(request):
    """Temporarily clear any running event loop set by Playwright's sync API.

    Playwright's sync_playwright().start() sets a running event loop via greenlets,
    which causes pytest-asyncio's Runner.run() to fail with
    "cannot be called from a running event loop". This fixture saves and clears the
    running loop before each non-e2e test, then restores it afterward.
    """
    test_path = Path(request.fspath)
    if _E2E_DIR in test_path.parents:
        yield
        return

    running_loop = asyncio._get_running_loop()
    if running_loop is not None:
        asyncio._set_running_loop(None)
    yield
    if running_loop is not None:
        asyncio._set_running_loop(running_loop)
