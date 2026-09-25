import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


@pytest.fixture()
def no_websockets(page: Page):
    """Attach before the test body, assert after — page-lifetime scoped."""
    opened: list[str] = []
    page.on("websocket", lambda ws: opened.append(ws.url))
    yield
    assert opened == [], f"WebSocket connection(s) opened in stateless mode: {opened}"


def test_stateless_event_round_trip_no_ws(
    page: Page, stateless_server: str, no_websockets
):
    page.goto(stateless_server)

    # (1) Counter round-trips through a stateless POST: click updates the DOM.
    expect(page.locator("#c")).to_have_text("0")
    page.click("#increment")
    expect(page.locator("#c")).to_have_text("1")

    # (2) The event was delivered as a POST to the stateless endpoint.
    posts = page.evaluate(
        "performance.getEntriesByType('resource')"
        ".filter(r => r.name.includes('/_pywire/stateless')).length"
    )
    assert posts >= 1, "no resource-timing entry for a POST to /_pywire/stateless"

    # (3) "No websocket ever" is enforced by the `no_websockets` fixture:
    #     the handler attaches before goto and asserts after the whole test.

    # (4) SPA navigation works end to end, and the stateless snapshot machinery
    #    survives it: the client re-extracts a fresh snapshot from each
    #    fetched document (relocate GET), so the page is still interactive on
    #    return and the snapshot round-trips on the next event.
    page.evaluate("window.__stateless_spa = true")
    page.click("#link-about")
    expect(page.locator("#about-title")).to_have_text("About Page")
    expect(page).to_have_url(f"{stateless_server}/about")
    assert (
        page.evaluate("window.__stateless_spa") is True
    )  # same document — no full reload

    page.click("#link-home")
    expect(page).to_have_url(f"{stateless_server}/")
    expect(page.locator("#c")).to_have_text(
        "0"
    )  # fresh snapshot from the re-fetched `/`
    page.click("#increment")
    expect(page.locator("#c")).to_have_text(
        "1"
    )  # re-extracted snapshot still round-trips
