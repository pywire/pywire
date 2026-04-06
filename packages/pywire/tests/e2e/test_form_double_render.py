from playwright.sync_api import Page, expect


def test_no_double_render_on_native_submit(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/form_double")

    try:
        # Check initial state
        expect(page.locator("#render-count")).to_have_text("Renders: 1")
    except Exception as e:
        print(f"\nDEBUG: Failure on page {page.url}")
        print(f"DEBUG: Content:\n{page.content()}")
        raise e

    expect(page.locator("#native-submit-count")).to_have_text("Submits: 0")

    # Submit native form
    page.click("#native-submit-btn")

    # Check updated state
    expect(page.locator("#native-submit-count")).to_have_text("Submits: 1")


def test_no_double_render_on_component_submit(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/form_double")

    # Check initial state
    expect(page.locator("#pywire-submit-count")).to_have_text("Submits: 0")

    # Submit PyWire component form
    page.click("#pywire-submit-btn")

    # Check updated state
    expect(page.locator("#pywire-submit-count")).to_have_text("Submits: 1")

    # Verify no doubling occurred visually
    # If doubling occurred, there would be two "#form-title" elements maybe?
    # But usually it's nested. conftest.py handles the nested check.
