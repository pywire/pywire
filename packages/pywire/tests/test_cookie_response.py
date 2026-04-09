"""Tests for BasePage cookie methods (set_cookie, delete_cookie)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from pywire.runtime.page import BasePage


def _make_page() -> BasePage:
    """Create a minimal BasePage for testing cookie methods."""
    pywire_app = SimpleNamespace(
        static_dir=None,
        static_url_path="/static",
        _is_dev_mode=False,
        _asset_hash_cache={},
        _asset_manifest=None,
        _asset_warned_missing=set(),
    )
    app_state = SimpleNamespace(pywire=pywire_app)
    app = SimpleNamespace(state=app_state)
    request = MagicMock()
    request.app = app

    page = BasePage.__new__(BasePage)
    page.request = request
    page._pending_cookies = []
    page._pending_navigation = None
    return page


class TestSetCookie:
    def test_queues_cookie(self) -> None:
        page = _make_page()
        page.set_cookie("session", "abc123", max_age=3600)

        assert len(page._pending_cookies) == 1
        cookie = page._pending_cookies[0]
        assert cookie["action"] == "set"
        assert cookie["key"] == "session"
        assert cookie["value"] == "abc123"
        assert cookie["max_age"] == 3600

    def test_default_values(self) -> None:
        page = _make_page()
        page.set_cookie("key", "val")

        cookie = page._pending_cookies[0]
        assert cookie["path"] == "/"
        assert cookie["samesite"] == "lax"
        assert cookie["secure"] is False
        assert cookie["httponly"] is False
        assert cookie["domain"] is None
        assert cookie["max_age"] is None

    def test_all_options(self) -> None:
        page = _make_page()
        page.set_cookie(
            "key",
            "val",
            max_age=100,
            expires=200,
            path="/app",
            domain="example.com",
            secure=True,
            httponly=True,
            samesite="strict",
        )

        cookie = page._pending_cookies[0]
        assert cookie["max_age"] == 100
        assert cookie["expires"] == 200
        assert cookie["path"] == "/app"
        assert cookie["domain"] == "example.com"
        assert cookie["secure"] is True
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "strict"


class TestDeleteCookie:
    def test_queues_deletion(self) -> None:
        page = _make_page()
        page.delete_cookie("session")

        assert len(page._pending_cookies) == 1
        cookie = page._pending_cookies[0]
        assert cookie["action"] == "delete"
        assert cookie["key"] == "session"
        assert cookie["path"] == "/"

    def test_with_domain(self) -> None:
        page = _make_page()
        page.delete_cookie("session", path="/app", domain="example.com")

        cookie = page._pending_cookies[0]
        assert cookie["path"] == "/app"
        assert cookie["domain"] == "example.com"


class TestMultipleCookies:
    def test_set_and_delete_in_same_request(self) -> None:
        page = _make_page()
        page.set_cookie("new_session", "xyz")
        page.delete_cookie("old_session")

        assert len(page._pending_cookies) == 2
        assert page._pending_cookies[0]["action"] == "set"
        assert page._pending_cookies[1]["action"] == "delete"


class TestFlushCookieCommands:
    def test_converts_to_commands(self) -> None:
        page = _make_page()
        page.set_cookie("session", "abc", max_age=3600, path="/")
        page.delete_cookie("old")

        commands = page._flush_cookie_commands()

        assert len(commands) == 2

        set_cmd = commands[0]
        assert set_cmd["cmd"] == "set_cookie"
        assert set_cmd["refId"] == "__page__"
        assert set_cmd["args"]["key"] == "session"
        assert set_cmd["args"]["value"] == "abc"
        assert set_cmd["args"]["max_age"] == 3600

        del_cmd = commands[1]
        assert del_cmd["cmd"] == "delete_cookie"
        assert del_cmd["args"]["key"] == "old"

    def test_clears_pending_after_flush(self) -> None:
        page = _make_page()
        page.set_cookie("session", "abc")

        page._flush_cookie_commands()

        assert len(page._pending_cookies) == 0

    def test_excludes_none_values_from_args(self) -> None:
        page = _make_page()
        page.set_cookie("key", "val")

        commands = page._flush_cookie_commands()
        args = commands[0]["args"]

        # None values should be excluded
        assert "max_age" not in args
        assert "expires" not in args
        assert "domain" not in args

    def test_empty_when_no_cookies(self) -> None:
        page = _make_page()

        commands = page._flush_cookie_commands()

        assert commands == []
