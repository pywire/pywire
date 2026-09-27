"""Browser regressions from the 2026-09 bug sweep."""

from playwright.sync_api import Page, expect


def test_server_clears_input_after_submit(page: Page, pywire_server: str):
    # #296: `draft.value = ""` clears the input the user just typed into.
    page.goto(f"{pywire_server}/bug_sweep")

    page.fill("#title-input", "hello")
    page.press("#title-input", "Enter")

    expect(page.locator("#items li")).to_have_text(["hello"])
    expect(page.locator("#title-input")).to_have_value("")


def test_reused_row_checkbox_follows_server_state(page: Page, pywire_server: str):
    # #296: filtering reuses the first <li>, whose box was checked; the
    # server's unchecked state must win over the stale DOM property.
    page.goto(f"{pywire_server}/bug_sweep")
    boxes = page.locator("#tasks input[type=checkbox]")
    expect(boxes).to_have_count(2)
    expect(boxes.nth(0)).to_be_checked()

    page.click("#filter")

    expect(page.locator("#tasks li")).to_have_count(1)
    expect(page.locator("#tasks li")).to_contain_text("write")
    expect(boxes.nth(0)).not_to_be_checked()
