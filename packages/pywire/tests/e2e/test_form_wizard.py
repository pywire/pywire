"""A wizard in a real browser: next, back, errors, and the final submit."""

from playwright.sync_api import Page, expect


def test_wizard_steps(page: Page, pywire_server):
    page.goto(f"{pywire_server}/wizard")
    expect(page.locator("#step")).to_have_text("account")
    page.fill('input[name="account.email"]', "a@b.co")
    page.click("#next")

    expect(page.locator("#step")).to_have_text("about")
    expect(page.locator("#next")).to_have_text("Create")
    page.fill('input[name="about.name"]', "A")
    page.click("#next")
    expect(page.locator("#err")).to_have_text("Use at least 2 characters")

    page.click("#back")
    expect(page.locator("#step")).to_have_text("account")
    expect(page.locator('input[name="account.email"]')).to_have_value("a@b.co")
    page.click("#next")

    expect(page.locator('input[name="about.name"]')).to_have_value("A")
    page.fill('input[name="about.name"]', "Al")
    page.click("#next")
    expect(page.locator("#done")).to_have_text("a@b.co/Al")
