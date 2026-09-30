"""List rows in a real browser: add and remove keep what the user typed."""

from playwright.sync_api import Page, expect


def test_add_and_remove_rows(page: Page, pywire_server):
    page.goto(f"{pywire_server}/rows")
    page.fill('input[name="customer"]', "Ann")

    page.click("#add")
    expect(page.locator(".row")).to_have_count(1)
    page.fill('input[name="items.0.name"]', "pen")
    page.click("#add")
    expect(page.locator(".row")).to_have_count(2)
    page.fill('input[name="items.1.name"]', "ink")
    expect(page.locator('input[name="customer"]')).to_have_value("Ann")

    page.locator(".row").first.get_by_role("button", name="Remove").click()
    expect(page.locator(".row")).to_have_count(1)
    expect(page.locator('input[name="items.0.name"]')).to_have_value("ink")

    page.click("#save")
    expect(page.locator("#done")).to_have_text("Ann:ink")
