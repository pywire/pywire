import pytest
from playwright.sync_api import Page, expect

def test_spa_navigation(page: Page, pywire_server: str):
    page.goto(pywire_server)
    
    expect(page.locator("h1")).to_have_text("Hello PyWire")
    
    # Click link to About page
    page.click("a:has-text('Go to About')")
    
    # Should navigate to /about
    expect(page).to_have_url(f"{pywire_server}/about")
    expect(page.locator("h1")).to_have_text("About Page")
    
    # Check that it didn't do a full reload (pywire-spa-meta should be preserved or updated via DOM)
    # Actually, we can check if a global window variable persists
    page.evaluate("window.spa_test_var = 'persisted'")
    
    # Go back to home
    page.click("a:has-text('Go Home')")
    expect(page).to_have_url(f"{pywire_server}/")
    expect(page.locator("h1")).to_have_text("Hello PyWire")
    
    # Check if variable persisted
    persisted = page.evaluate("window.spa_test_var")
    assert persisted == "persisted", "Full page reload occurred during navigation"

def test_navigation_to_error_page(page: Page, pywire_server: str):
    page.goto(pywire_server)
    
    # Navigate to a non-existent page
    page.goto(f"{pywire_server}/non-existent")
    
    # Should show 404 or redirect to error page?
    # By default PyWire handles 404s.
    # In basic_app, there is an error.wire page.
    # Actually, let's just check for a 404 status code if possible, 
    # but Playwright goto throws error if response is not 2xx-3xx in some cases.
    
    response = page.goto(f"{pywire_server}/non-existent")
    assert response.status == 404
