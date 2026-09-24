"""E2E tests for the ``@poll`` directive — both transports.

The poll.wire fixture has ``@poll.every-200={tick()}`` on an element wrapped in
``$if={not done}``; tick() counts to 5 and flips ``done``. The unmount is the
stop condition: no ``.while`` exists, so proving poll stops means proving the
polled element leaves the DOM and no further dispatches arrive.

Transport-identical behavior is the point: the same page is asserted on the
stateless server (ticks arrive as POSTs to /_pywire/stateless) and on the
stateful WebSocket server with the same DOM outcomes.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


@pytest.fixture()
def stateless_posts(page: Page):
    """Collect every POST to the stateless event endpoint for this page."""
    posts: list[str] = []
    page.on(
        "request",
        lambda r: posts.append(r.url)
        if r.method == "POST" and "/_pywire/stateless" in r.url
        else None,
    )
    yield posts


def test_poll_ticks_as_stateless_posts_and_stops(
    page: Page, stateless_server: str, stateless_posts: list[str]
):
    page.goto(f"{stateless_server}/poll")

    # Codegen wiring is visible in the DOM.
    polled = page.locator("#tick-el")
    expect(polled).to_have_attribute("data-pw-poll-every", "200")
    assert polled.get_attribute("data-pw-poll") is not None

    # Ticks advance the rendered counter up to the stop condition.
    expect(page.locator("#count")).to_have_text("0")
    expect(page.locator("#count")).to_have_text("5", timeout=10_000)

    # Ticks arrived as repeated stateless POSTs (one per dispatch).
    assert len(stateless_posts) >= 3, (
        f"expected repeated poll POSTs, got {stateless_posts}"
    )

    # STOP: the condition flipped, the polled element unmounted…
    expect(page.locator("#tick-el")).to_have_count(0)
    expect(page.locator("#done-el")).to_be_visible()

    # …and no further poll POSTs arrive within a quiet window (6 intervals).
    n = len(stateless_posts)
    page.wait_for_timeout(1500)
    assert len(stateless_posts) == n, (
        f"poll POSTs continued after unmount: {stateless_posts[n:]}"
    )


def test_poll_same_behavior_over_websocket(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/poll")

    # Identical DOM outcomes on the stateful tier: counter advances…
    expect(page.locator("#count")).to_have_text("0")
    expect(page.locator("#count")).to_have_text("5", timeout=10_000)

    # …and stops identically via conditional-render unmount.
    expect(page.locator("#tick-el")).to_have_count(0)
    expect(page.locator("#done-el")).to_be_visible()

    # Quiet window: the counter must not drift after the stop.
    page.wait_for_timeout(1500)
    expect(page.locator("#count")).to_have_text("5")
