# import pytest
from pywire.runtime.page import BasePage
from pywire.runtime.router import Router, URLHelper


class MockPage(BasePage):
    pass


def test_router_typed_params() -> None:
    router = Router()
    router.add_route("/test/:id:int", MockPage, "test")

    # Match valid int
    match = router.match("/test/123")
    assert match is not None
    cls, params, name = match
    assert params["id"] == "123"  # Currently returning strings
    assert name == "test"

    # Fail string
    match = router.match("/test/abc")
    assert match is None


def test_router_dict_path() -> None:
    router = Router()
    router.add_route("/main", MockPage, "main")
    router.add_route("/other/:id", MockPage, "other")

    match = router.match("/main")
    assert match is not None
    _, _, name = match
    assert name == "main"

    match = router.match("/other/123")
    assert match is not None
    _, params, name = match
    assert name == "other"
    assert params["id"] == "123"


def test_url_helper() -> None:
    routes = {"main": "/test", "detail": "/test/:id:int", "edit": "/test/{id}/edit"}
    helper = URLHelper(routes)

    assert helper["main"].format() == "/test"
    assert helper["detail"].format(id=123) == "/test/123"
    assert helper["edit"].format(id=456) == "/test/456/edit"


def test_router_root_path() -> None:
    router = Router()
    router.add_route("/", MockPage, "root")

    match = router.match("/")
    assert match is not None
    _, _, name = match
    assert name == "root"


if __name__ == "__main__":
    # Rudimentary test runner if pytest not available
    try:
        test_router_typed_params()
        test_router_dict_path()
        test_url_helper()
        test_router_root_path()
        print("All tests passed!")
    except AssertionError as e:
        print(f"Test failed: {e}")
        raise
