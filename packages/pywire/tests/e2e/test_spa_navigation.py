import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_spa_navigation_script_execution(page: Page, pywire_server: str):
    # Go to the home page
    page.goto(pywire_server)
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate to About page via PJAX link
    # PyWire uses $reload="pjax" normally. Let's see how we set it up.
    # We used data-reload="pjax" or $reload ? The issue description says $reload="pjax" or similar.
    # PyWire core usually uses a custom attribute or just intercepts standard links if router is enabled.
    # Let's assume the link works as configured.
    page.click("#link-about")

    # Verify we are on the About page without a full reload
    expect(page.locator("#about-title")).to_have_text("About Page")

    # Wait for the script to execute and set the attribute
    expect(page.locator("body")).to_have_attribute("data-script-runs", "1")

    # Navigate back home
    page.click("#link-home")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate to About page AGAIN via PJAX link
    page.click("#link-about")
    expect(page.locator("#about-title")).to_have_text("About Page")

    # Verify the script executed exactly ONCE MORE (total 2 times)
    # This proves the script is run on subsequent visits, not cached and ignored,
    # and not duplicated per visit.
    expect(page.locator("body")).to_have_attribute("data-script-runs", "2")
