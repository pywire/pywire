import pytest
from playwright.sync_api import Page, expect

@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")
    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))

def test_refs_and_expose(page: Page, pywire_server):
    page.goto(f"{pywire_server}/refs_expose")
    
    # 1. Initial State
    expect(page.locator("#comp-count")).to_have_text("Count: 0")
    expect(page.locator("#log li")).to_have_count(0)
    
    # 2. Call Increment
    page.click("#btn-increment")
    expect(page.locator("#comp-count")).to_have_text("Count: 1")
    expect(page.locator("#log li")).to_have_text(["Called increment, new count: 1"])
    
    # 3. Multiple Increments
    page.click("#btn-increment")
    page.click("#btn-increment")
    expect(page.locator("#comp-count")).to_have_text("Count: 3")
    expect(page.locator("#log li")).to_have_count(3)
    expect(page.locator("#log li").last).to_have_text("Called increment, new count: 3")
    
    # 4. Invalid Method Call
    page.click("#btn-invalid")
    expect(page.locator("#log li")).to_have_count(4)
    # Check that it caught the AttributeError
    expect(page.locator("#log li").last).to_contain_text("Caught expected error")
