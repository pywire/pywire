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


def test_bound_form_submits_the_model(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")

    # Fill form
    page.fill('input[name="name"]', "Test User")
    page.fill('input[name="age"]', "25")

    # Submit
    page.click("#btn-submit-form")

    # The handler receives a validated User; the page shows model_dump()
    expect(page.locator("#submitted-data")).to_contain_text('"name": "Test User"')
    expect(page.locator("#submitted-data")).to_contain_text('"age": 25')


def test_server_enforces_the_model_when_html_is_edited(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")

    age = page.locator('input[name="age"]')
    expect(age).to_have_attribute("min", "0")
    # A client that strips the constraint still can't get past the server
    page.evaluate(
        'document.querySelector(\'input[name="age"]\').removeAttribute("min")'
    )
    page.fill('input[name="age"]', "-5")

    page.click("#btn-submit-form")

    error_msg = page.locator('.error-msg[data-for="age"]')
    expect(error_msg).to_have_text("Must be 0 or more")
    expect(page.locator("#submitted-data")).to_have_text("None")
    expect(age).to_have_attribute("aria-invalid", "true")
    expect(age).to_have_value("-5")
