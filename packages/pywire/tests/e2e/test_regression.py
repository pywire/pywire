import pytest
from playwright.sync_api import Page, expect

@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")
    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))



def test_missing_static_assets_issue_1(page: Page, pywire_server: str):
    # Listen to network requests to ensure no 404s for /_pywire/static files
    failed_requests = []
    
    def handle_response(response):
        if "_pywire/static" in response.url and response.status >= 400:
            failed_requests.append({'url': response.url, 'status': response.status})

    page.on("response", handle_response)
    
    # Load a basic page
    page.goto(f"{pywire_server}")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    assert len(failed_requests) == 0, f"Failed to load static assets: {failed_requests}"

import time
from pathlib import Path

@pytest.mark.xfail(reason="Issue #4: Hot Reloading with Components")
def test_hot_reloading_issue_4(page: Page, pywire_server: str, test_app_dir: str):
    # Go to hot reload test page
    page.goto(f"{pywire_server}/hot_reload")
    expect(page.locator("#hot-reload-title")).to_have_text("Hot Reloading Test")
    
    # Assert initial text rendered by ChildComponent
    expect(page.locator("#child-content")).to_have_text("Initial Text")
    
    # Simulate a developer editing the ChildComponent code
    child_path = Path(test_app_dir) / "components" / "child.wire"
    
    # Keep the original content to restore it at the end of the test
    # (Since test_app_dir is per session, other tests modifying it could interfere, 
    # but this test runs sequentially so restoring is safest)
    original_content = child_path.read_text()
    
    try:
        new_content = original_content.replace("Initial Text", "Updated Text")
        child_path.write_text(new_content)
        
        # PyWire watcher might take a fraction of a second to detect the file change
        # and send the websocket reload signal. Playwright's expect handles retries.
        
        # Verify the text updates without page reload (hot reload)
        expect(page.locator("#child-content")).to_have_text("Updated Text", timeout=10000)
    finally:
        # Restore the original file to keep the fixture clean for subsequent tests
        child_path.write_text(original_content)
