import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def _goto_ref_test(page: Page, pywire_server: str):
    """Navigate to the ref test page and wait for it to be ready."""
    page.goto(f"{pywire_server}/ref_test")
    expect(page.locator("#ref-test-title")).to_have_text("Ref System Test")


# --- Input Value Sync Tests ---


def test_input_ref_value_syncs_to_server(page: Page, pywire_server: str):
    """Type into an input with $ref, wait for debounced sync, then read value on server."""
    _goto_ref_test(page, pywire_server)

    # Type into the text input
    page.fill("#text-input", "hello world")

    # Wait for debounced ref_sync (250ms debounce + network round trip)
    page.wait_for_timeout(500)

    # Click "Read Text Value" to ask the server to read the ref's synced value
    page.click("#read-text-btn")

    # The server handler sets value_display to the ref's current value
    expect(page.locator("#value-display")).to_have_text("hello world")


def test_number_input_ref_value_syncs(page: Page, pywire_server: str):
    """Number input ref value syncs correctly."""
    _goto_ref_test(page, pywire_server)

    page.fill("#num-input", "42")
    page.wait_for_timeout(500)

    page.click("#read-num-btn")
    expect(page.locator("#num-display")).to_have_text("42")


# --- Focus / Blur Tests ---


def test_ref_focus(page: Page, pywire_server: str):
    """ref.focus() focuses the target element."""
    _goto_ref_test(page, pywire_server)

    # Click somewhere else first to ensure text-input is not focused
    page.click("#ref-test-title")
    expect(page.locator("#text-input")).not_to_be_focused()

    # Click the focus button
    page.click("#focus-btn")

    # The server queues a focus command, client executes it
    expect(page.locator("#text-input")).to_be_focused()


def test_ref_blur(page: Page, pywire_server: str):
    """ref.blur() blurs the target element."""
    _goto_ref_test(page, pywire_server)

    # First focus the input directly
    page.click("#text-input")
    expect(page.locator("#text-input")).to_be_focused()

    # Now blur via server command
    page.click("#blur-btn")

    expect(page.locator("#text-input")).not_to_be_focused()


# --- CSS Class Tests ---


def test_ref_add_class(page: Page, pywire_server: str):
    """ref.add_class() adds a CSS class to the element."""
    _goto_ref_test(page, pywire_server)

    # Verify the class is not present initially
    expect(page.locator("#text-input")).not_to_have_class("highlighted")

    # Add the class
    page.click("#add-class-btn")

    # Wait for the DOM update after the server response
    expect(page.locator("#text-input.highlighted")).to_be_visible()


def test_ref_remove_class(page: Page, pywire_server: str):
    """ref.remove_class() removes a CSS class from the element."""
    _goto_ref_test(page, pywire_server)

    # First add the class
    page.click("#add-class-btn")
    expect(page.locator("#text-input.highlighted")).to_be_visible()

    # Now remove it
    page.click("#remove-class-btn")

    # Verify the class is gone
    expect(page.locator("#text-input.highlighted")).to_have_count(0)


def test_ref_toggle_class(page: Page, pywire_server: str):
    """ref.toggle_class() toggles a CSS class on the element."""
    _goto_ref_test(page, pywire_server)

    # Initially no "toggled" class
    expect(page.locator("#generic-div.toggled")).to_have_count(0)

    # Toggle on
    page.click("#toggle-class-btn")
    expect(page.locator("#generic-div.toggled")).to_be_visible()

    # Toggle off
    page.click("#toggle-class-btn")
    expect(page.locator("#generic-div.toggled")).to_have_count(0)


# --- Attribute Tests ---


def test_ref_set_attribute(page: Page, pywire_server: str):
    """ref.set_attribute() sets an attribute on the element."""
    _goto_ref_test(page, pywire_server)

    page.click("#set-attr-btn")

    expect(page.locator("#generic-div")).to_have_attribute("data-custom", "test-value")


def test_ref_remove_attribute(page: Page, pywire_server: str):
    """ref.remove_attribute() removes an attribute from the element."""
    _goto_ref_test(page, pywire_server)

    # First set the attribute
    page.click("#set-attr-btn")
    expect(page.locator("#generic-div")).to_have_attribute("data-custom", "test-value")

    # Now remove it
    page.click("#remove-attr-btn")

    # Verify attribute is gone
    has_attr = page.locator("#generic-div").evaluate(
        "el => el.hasAttribute('data-custom')"
    )
    assert has_attr is False, "data-custom attribute should have been removed"


# --- Form Ref Tests ---


def test_form_ref_reset(page: Page, pywire_server: str):
    """form ref.reset() clears form fields on the client."""
    _goto_ref_test(page, pywire_server)

    # Fill in form fields
    page.fill("#form-username", "testuser")
    page.fill("#form-email", "test@example.com")
    page.fill("#form-age", "25")

    # Verify fields are filled
    expect(page.locator("#form-username")).to_have_value("testuser")

    # Reset the form via server command
    page.click("#form-reset-btn")

    # Verify fields are cleared
    expect(page.locator("#form-username")).to_have_value("")
    expect(page.locator("#form-email")).to_have_value("")
    expect(page.locator("#form-age")).to_have_value("")


def test_form_ref_data_is_empty_without_submission(page: Page, pywire_server: str):
    """form ref.data is empty when no form event has triggered data collection.

    Form data is only collected during event handling on the form element itself,
    not via passive ref_sync like input values.
    """
    _goto_ref_test(page, pywire_server)

    # Fill in form fields on the client
    page.fill("#form-username", "alice")
    page.fill("#form-email", "alice@example.com")
    page.fill("#form-age", "30")

    page.wait_for_timeout(500)

    # Read form data on server - should be empty since no form event fired
    page.click("#read-form-btn")

    # The server-side form ref.data is {} because form data is only populated
    # when events fire on the form element (e.g., submit)
    expect(page.locator("#form-data-display")).to_have_text("{}")


# --- Ref Auto-Detection Tests ---


def test_ref_auto_detects_input_type(page: Page, pywire_server: str):
    """ref() on an <input> should auto-detect as InputElement and support .value."""
    _goto_ref_test(page, pywire_server)

    page.fill("#text-input", "auto-detect-test")
    page.wait_for_timeout(500)

    # If auto-detection works, read_text_value will successfully read text_input.value
    page.click("#read-text-btn")
    expect(page.locator("#value-display")).to_have_text("auto-detect-test")


# --- Operation Log Tests ---


def test_operations_are_logged(page: Page, pywire_server: str):
    """Each operation appends to the operation log for traceability."""
    _goto_ref_test(page, pywire_server)

    page.click("#focus-btn")
    expect(page.locator("#operation-log .log-entry")).to_have_count(1)
    expect(page.locator("#operation-log .log-entry").first).to_contain_text(
        "focus called"
    )

    page.click("#blur-btn")
    expect(page.locator("#operation-log .log-entry")).to_have_count(2)

    page.click("#add-class-btn")
    expect(page.locator("#operation-log .log-entry")).to_have_count(3)
    expect(page.locator("#operation-log .log-entry").last).to_contain_text(
        "add_class highlighted"
    )


# --- Scroll Test ---


def test_ref_scroll_to(page: Page, pywire_server: str):
    """ref.scroll_to() queues a scroll command without error."""
    _goto_ref_test(page, pywire_server)

    # This mainly verifies the command doesn't throw an error
    page.click("#scroll-btn")

    # Verify the operation was logged (proves the server handler ran successfully)
    expect(page.locator("#operation-log .log-entry").last).to_contain_text(
        "scroll_to called"
    )
