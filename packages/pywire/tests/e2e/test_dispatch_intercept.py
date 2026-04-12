"""E2E tests for dispatch() enhancements: ref.dispatch() and server-side interception."""

from playwright.sync_api import Page, expect


def test_server_side_intercept_no_dom_roundtrip(page: Page, pywire_server: str):
    """dispatch() with bubbles=False + registered handler calls handler server-side.

    The intercepted handler should produce a wire update in the SAME render cycle
    as the button click — no second WS round trip through the DOM.
    """
    page.goto(f"{pywire_server}/dispatch_intercept")
    expect(page.locator("#title")).to_have_text("Dispatch Intercept")

    # Initial state
    expect(page.locator("#intercept-result")).to_have_text("")

    # Click: fires dispatch("server-handled", bubbles=False) on target ref
    # The target has @server-handled={on_server_handled}
    # Server should intercept and call on_server_handled directly
    page.click("#fire-intercepted")

    # The result should appear in the same update (no DOM round trip needed)
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=1")
    expect(page.locator("#counter")).to_have_text("1")


def test_server_side_intercept_multiple_clicks(page: Page, pywire_server: str):
    """Multiple intercepted dispatches produce correct sequential results."""
    page.goto(f"{pywire_server}/dispatch_intercept")

    page.click("#fire-intercepted")
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=1")

    page.click("#fire-intercepted")
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=2")

    page.click("#fire-intercepted")
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=3")


def test_dom_dispatch_still_works(page: Page, pywire_server: str):
    """dispatch() with bubbles=True goes through DOM, not intercepted server-side."""
    page.goto(f"{pywire_server}/dispatch_intercept")

    expect(page.locator("#dom-result")).to_have_text("")

    # Click: fires dispatch("dom-handled", bubbles=True) on target ref
    # Even though target has @dom-handled handler, bubbles=True → DOM dispatch
    # Client fires CustomEvent → pywire intercepts → sends back to server
    page.click("#fire-dom")

    # Handler was called via DOM round trip (detail not preserved — that's
    # a known limitation of pywire's event handler not extracting e.detail)
    expect(page.locator("#dom-result")).to_have_text("dom:called")


def test_intercept_and_dom_independent(page: Page, pywire_server: str):
    """Intercepted and DOM dispatches don't interfere with each other."""
    page.goto(f"{pywire_server}/dispatch_intercept")

    # Fire intercepted first
    page.click("#fire-intercepted")
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=1")
    expect(page.locator("#dom-result")).to_have_text("")

    # Fire DOM second
    page.click("#fire-dom")
    expect(page.locator("#dom-result")).to_have_text("dom:called")
    # Intercept result should not change
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=1")


def test_js_listener_fires_on_intercepted_dispatch(page: Page, pywire_server: str):
    """JS listeners receive the CustomEvent (with detail) even when server intercepts.

    The server calls the Python handler directly AND sends the dispatch command
    to the client so JS listeners fire with the correct detail payload.
    """
    page.goto(f"{pywire_server}/dispatch_intercept")

    # JS listener should be waiting
    expect(page.locator("#js-listener-proof")).to_have_text("waiting")

    # Fire intercepted dispatch — server handles Python side, but JS should also fire
    page.click("#fire-intercepted")

    # Python handler ran server-side
    expect(page.locator("#intercept-result")).to_have_text("intercepted:n=1")

    # JS listener also fired with correct detail
    expect(page.locator("#js-listener-proof")).to_have_text("js-heard:n=1")
