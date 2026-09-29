"""An app served under /demo in a real browser, live and stateless."""

import re

from playwright.sync_api import Page, expect


def test_app_under_prefix(page: Page, base_path_server: str):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    root = base_path_server.rstrip("/")

    page.goto(f"{root}/demo/")
    expect(page.locator("#title")).to_have_text("Home")
    # Static file under the prefix.
    expect(page.locator("#title")).to_have_css("color", "rgb(1, 2, 3)")

    # Events reach the server under the prefix.
    page.click("#bump")
    expect(page.locator("#count")).to_have_text("1")

    # SPA navigation keeps the prefix and doesn't reload the page.
    page.evaluate("window.__same_document = true")
    page.click("#to-about")
    expect(page.locator("#title")).to_have_text("About")
    assert page.url == f"{root}/demo/about"
    assert page.evaluate("window.__same_document") is True

    # navigate("/") from a handler lands on the app's index, not the site's.
    page.click("#go-home")
    expect(page.locator("#title")).to_have_text("Home")
    expect(page).to_have_url(re.compile(r"/demo/$"))

    page.click("#bump")
    expect(page.locator("#count")).to_have_text("1")
    assert errors == []
