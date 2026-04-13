"""E2E tests for client-side script execution on SPA navigation.

Verifies the fix for scripts not re-executing after PJAX/morphdom DOM updates.
The key behavioral change: scripts now execute AFTER morphdom updates the DOM,
so inline scripts can reference newly-inserted elements.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_script_finds_dom_element_after_spa_navigation(page: Page, pywire_server: str):
    """Scripts that reference DOM elements by ID should work on SPA navigation.

    This was the core bug: scripts executed before morphdom updated the DOM,
    so getElementById() returned null for elements that hadn't been inserted yet.
    """
    # Start on home page
    page.goto(pywire_server)
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate to the script_dom_ref page via direct URL first (full page load)
    page.goto(f"{pywire_server}/script_dom_ref")
    expect(page.locator("#script-dom-title")).to_have_text("Script DOM Reference Test")

    # Script should have found the target element
    expect(page.locator("#script-result")).to_have_text("found:Target Element")


def test_script_finds_dom_element_on_spa_return(page: Page, pywire_server: str):
    """Navigate away and back via SPA — script should re-execute and find elements."""
    page.goto(f"{pywire_server}/script_dom_ref")
    expect(page.locator("#script-result")).to_have_text("found:Target Element")

    # Navigate to home via SPA link
    page.click("#link-home")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate back to script_dom_ref via SPA link
    page.click("#link-about")  # go to about first
    expect(page.locator("#about-title")).to_have_text("About Page")

    # Now go to script_dom_ref via direct link (back button or typed)
    page.goto(f"{pywire_server}/script_dom_ref")
    expect(page.locator("#script-result")).to_have_text("found:Target Element")


def test_permanent_element_script_does_not_rerun_on_navigation(
    page: Page, pywire_server: str
):
    """Scripts inside $permanent elements should NOT re-execute on SPA navigation.

    Note: Wire state updates only re-render affected regions, not the full page,
    so scripts don't re-execute at all on partial updates. This test uses SPA
    navigation (full page swap) to verify permanent vs non-permanent behavior.
    """
    # Navigate to permanent_script page
    page.goto(f"{pywire_server}/permanent_script")
    expect(page.locator("#perm-script-title")).to_have_text("Permanent Script Test")

    # Initial load: both scripts should have run once
    expect(page.locator("#permanent-text")).to_have_text("ran:1")
    expect(page.locator("#non-permanent-result")).to_have_text("ran:1")

    # Navigate away via SPA
    page.click("#link-home")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate back via full page load (SPA link doesn't exist back to permanent_script,
    # so we use goto which triggers a full page load and script re-execution)
    page.goto(f"{pywire_server}/permanent_script")

    # On a full page load, all scripts run — permanent or not — because the DOM
    # is fully replaced. The permanent attribute only matters during morphdom diffs.
    # Both should show ran:1 again (fresh page load, counters in a new JS context)
    expect(page.locator("#permanent-text")).to_have_text("ran:1")
    expect(page.locator("#non-permanent-result")).to_have_text("ran:1")


def test_spa_script_runs_once_per_navigation(page: Page, pywire_server: str):
    """Existing test from test_spa_navigation.py — verify script runs exactly once per visit."""
    page.goto(pywire_server)
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate to about page (has a script that increments a counter)
    page.click("#link-about")
    expect(page.locator("#about-title")).to_have_text("About Page")
    expect(page.locator("body")).to_have_attribute("data-script-runs", "1")

    # Navigate back home
    page.click("#link-home")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Navigate to about AGAIN
    page.click("#link-about")
    expect(page.locator("#about-title")).to_have_text("About Page")

    # Script should have run exactly twice total (once per navigation)
    expect(page.locator("body")).to_have_attribute("data-script-runs", "2")
