import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_form_double_render(page: Page, pywire_server: str):
    # Go to the form page
    page.goto(f"{pywire_server}/form_double")
    expect(page.locator("#form-title")).to_have_text("Form Test")

    # Native Form Test — verify handler fires exactly once (no double event)
    expect(page.locator("#render-count")).to_have_text("Renders: 1")
    expect(page.locator("#native-submit-count")).to_have_text("Submits: 0")

    page.click("#native-submit-btn")

    expect(page.locator("#native-submit-count")).to_have_text("Submits: 1")
    # render_count is init-time code, not re-evaluated on partial updates
    expect(page.locator("#render-count")).to_have_text("Renders: 1")

    # Reset page for PyWire form test
    page.goto(f"{pywire_server}/form_double")

    # PyWire Form Test — verify component form also fires handler exactly once
    expect(page.locator("#render-count")).to_have_text("Renders: 1")
    expect(page.locator("#pywire-submit-count")).to_have_text("Submits: 0")

    page.click("#pywire-submit-btn")

    expect(page.locator("#pywire-submit-count")).to_have_text("Submits: 1")
    expect(page.locator("#render-count")).to_have_text("Renders: 1")


def test_form_input_binding(page: Page, pywire_server: str):
    # Basic input binding test (regression/coverage)
    # Need a fixture for this, or just test if typing in the form field works
    pass
