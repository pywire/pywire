import pytest
import json
from playwright.sync_api import Page, expect

@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")
    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))

def test_error_boundary_trace(page: Page, pywire_server: str):
    # Navigate to the error test page
    page.goto(f"{pywire_server}/error")
    
    # Ensure page loaded
    expect(page.locator("h1")).to_have_text("Error Boundaries Test")
    
    # Track console messages
    # We need to expose a way for the browser context to access console logs
    page.evaluate("window.console_logs = []")
    page.on("console", lambda msg: page.evaluate("window.console_logs.push(%s)" % json.dumps(msg.text)))
    
    # Trigger the error
    page.click("#btn-error")
    
    # Wait for the traceback to appear in console logs
    page.wait_for_function("""
        () => window.console_logs.some(log => 
            log.includes('error.wire') && 
            (log.includes('Traceback') || log.includes('page.py'))
        )
    """, timeout=5000)
