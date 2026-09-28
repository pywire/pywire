import pytest


@pytest.fixture(autouse=True)
def _isolate_prebuilt_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generated deploy entrypoints set PYWIRE_PREBUILT=1 when a test runs
    them in-process; undo it so later tests' apps still load their pages."""
    monkeypatch.setenv("PYWIRE_PREBUILT", "0")
