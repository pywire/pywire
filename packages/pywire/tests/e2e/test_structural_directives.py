import pytest
from playwright.sync_api import Page, expect

def test_structural_if_show(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/structural")
    
    expect(page.locator("h1")).to_have_text("Structural Directives Test")
    
    # Initial state: visible
    expect(page.locator("#if-element")).to_be_visible()
    expect(page.locator("#show-element")).to_be_visible()
    
    # Toggle
    page.click("#btn-toggle")
    
    # Should be hidden
    expect(page.locator("#if-element")).to_be_hidden()
    expect(page.locator("#show-element")).to_be_hidden()
    
    # Verify $if removes from DOM
    assert page.locator("#if-element").count() == 0, "$if did not remove element from DOM"
    # Verify $show hides via CSS
    expect(page.locator("#show-element")).to_have_css("display", "none")

def test_structural_for_loop(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/structural")
    
    try:
        # Initial items
        items = page.locator(".list-item")
        expect(items).to_have_count(2)
        expect(items.nth(0)).to_have_text("Apple")
        expect(items.nth(1)).to_have_text("Banana")
        
        # Add item
        page.click("#btn-add")
        
        # Should have 3 items
        expect(items).to_have_count(3)
        expect(items.nth(2)).to_have_text("Cherry")
    except Exception as e:
        print(f"\nDEBUG: Failure on page {page.url}")
        print(f"DEBUG: Content:\n{page.content()}")
        raise e
