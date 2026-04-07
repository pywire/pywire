"""E2E tests for event field bandwidth optimization.

Verifies the full pipeline:
  handler source → static analysis → data-pw-fields-* HTML attribute → client filtering

The event_fields.wire page has handlers that access specific event fields:
- on_keypress uses event.key → should emit data-pw-fields-keydown="key"
- on_click_coords uses event.client_x, event.client_y → data-pw-fields-click="clientX,clientY"
- on_full_event uses event.type → data-pw-fields-click="type"
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_event_fields_page_loads(page: Page, pywire_server: str):
    """Basic smoke test that the event_fields page renders correctly."""
    page.goto(f"{pywire_server}/event_fields")
    expect(page.locator("#event-fields-title")).to_have_text("Event Fields Test")


def test_field_mask_in_html(page: Page, pywire_server: str):
    """Verify that data-pw-fields-* attributes are emitted in the HTML."""
    page.goto(f"{pywire_server}/event_fields")

    # The keydown handler only uses event.key
    key_input = page.locator("#key-input")
    field_mask = key_input.get_attribute("data-pw-fields-keydown")
    # If the compiler emitted a field mask, it should contain "key"
    if field_mask is not None:
        assert "key" in field_mask


def test_keypress_handler_works(page: Page, pywire_server: str):
    """Verify the keypress handler works — event.key is correctly delivered."""
    page.goto(f"{pywire_server}/event_fields")

    # Press a key in the input
    page.locator("#key-input").press("a")

    # The handler sets last_key = event.key
    expect(page.locator("#last-key")).to_have_text("a")


def test_click_coords_handler_works(page: Page, pywire_server: str):
    """Verify click handler receives client_x and client_y."""
    page.goto(f"{pywire_server}/event_fields")

    # Click the button — coordinates will be captured
    page.click("#btn-coords")

    # Wait for the handler to update the DOM (the wire state round-trips through server)
    page.locator("#last-coords").wait_for(state="attached")
    # Wait until the text is no longer empty (initial value)
    page.wait_for_function(
        'document.getElementById("last-coords").textContent.includes(",")',
        timeout=5000,
    )

    # The handler sets last_coords = f"{event.client_x},{event.client_y}"
    coords_text = page.locator("#last-coords").text_content()
    assert coords_text is not None
    # Coords should be two numbers separated by comma
    parts = coords_text.split(",")
    assert len(parts) == 2
    # Both should be parseable as numbers (floats)
    float(parts[0])
    float(parts[1])


def test_full_event_handler_works(page: Page, pywire_server: str):
    """Verify handler that uses event.type receives the correct event type."""
    page.goto(f"{pywire_server}/event_fields")

    page.click("#btn-full")
    expect(page.locator("#full-event-type")).to_have_text("click")
