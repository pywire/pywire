"""A bound <select> shows what the server renders when the form is reset or
loaded, instead of keeping the user's earlier choice."""

from playwright.sync_api import Page, expect


def test_reset_clears_the_selects(page: Page, pywire_server):
    page.goto(f"{pywire_server}/select_reset")
    page.fill("#pick-title", "first")
    page.select_option("#pick-size", "m")
    page.select_option("#pick-owner", "ada")
    page.click("#pick-save")

    expect(page.locator("#pick-saved")).to_have_text("first/m/ada")
    expect(page.locator("#pick-size")).to_have_value("s")
    expect(page.locator("#pick-owner")).to_have_value("")


def test_load_sets_the_selects(page: Page, pywire_server):
    page.goto(f"{pywire_server}/select_reset")
    page.select_option("#pick-owner", "ada")
    page.click("#pick-load")

    expect(page.locator("#pick-title")).to_have_value("loaded")
    expect(page.locator("#pick-size")).to_have_value("l")
    expect(page.locator("#pick-owner")).to_have_value("bob")


def test_a_rerender_keeps_the_users_choice(page: Page, pywire_server):
    page.goto(f"{pywire_server}/select_reset")
    page.select_option("#pick-owner", "bob")
    # Typing re-renders the form (blur validation); the choice stays.
    page.fill("#pick-title", "x")
    page.locator("#pick-title").blur()
    page.fill("#pick-title", "")
    page.locator("#pick-title").blur()
    expect(page.locator("#pick-owner")).to_have_value("bob")
