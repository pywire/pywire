import pytest
from playwright.sync_api import Page, expect

def test_native_form_submit_prevent(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/input_binding")
    
    # Fill input
    page.fill("#name-input", "Antigravity")
    
    # Submit form
    page.click("#native-submit")
    
    # Check that it didn't reload (SPA behavior) and updated the display
    expect(page.locator("#name-display")).to_have_text("Hello, Antigravity!")
    
    # Confirm it's still the same page (no full reload)
    # The input should still have the value
    expect(page.locator("#name-input")).to_have_value("Antigravity")

def test_component_form_pydantic_validation(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")
    
    # Fill form
    page.fill('input[name="name"]', "Test User")
    page.fill('input[name="age"]', "25")
    
    # Submit
    page.click("#btn-submit-form")
    
    # Check submitted data display
    # It should look like {"name": "Test User", "age": 25} (serialized by json.dumps)
    # Note: Pydantic might have converted age to int
    expect(page.locator("#submitted-data")).to_contain_text('"name": "Test User"')
    expect(page.locator("#submitted-data")).to_contain_text('"age": 25')

def test_component_form_validation_error(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")
    
    # Fill with invalid age (string instead of number)
    # We use evaluate to bypass Playwright/browser type="number" guard for "not-a-number"
    page.evaluate('document.querySelector(\'input[name="age"]\').value = "not-a-number"')
    page.locator('input[name="age"]').dispatch_event("input")
    
    # Submit
    page.click("#btn-submit-form")
    
    # Submitted data should still be None
    expect(page.locator("#submitted-data")).to_have_text("None")
    
    # Check for error message
    # Pydantic usually gives "Input should be a valid integer"
    error_msg = page.locator('.error-msg[data-for="age"]')
    expect(error_msg).not_to_be_empty()
    expect(error_msg).to_contain_text("Input should be a valid integer")
