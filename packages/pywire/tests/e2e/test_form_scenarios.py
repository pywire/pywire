from playwright.sync_api import Page, expect


def test_native_form_submit(page: Page, pywire_server):
    page.goto(f"{pywire_server}/form_scenarios")

    page.fill("#native-user", "testuser")
    page.fill("#native-email", "test@example.com")
    page.click("#btn-native-submit")

    expect(page.locator("#native-result")).to_have_text(
        "Captured: testuser - test@example.com"
    )


def test_comp_form_validation(page: Page, pywire_server):
    page.goto(f"{pywire_server}/form_scenarios")

    # 1. Test validation error (min_length)
    page.fill("#comp-user", "ab")
    page.fill("#comp-age", "25")
    page.click("#btn-comp-submit")

    expect(page.locator("#err-user")).to_be_visible()
    expect(page.locator("#comp-result")).to_have_text("")

    # 2. Fix error
    page.fill("#comp-user", "alice")
    page.click("#btn-comp-submit")

    expect(page.locator("#err-user")).to_be_hidden()
    expect(page.locator("#comp-result")).to_have_text("User: alice (Age: 25)")


def test_comp_form_manual_submit(page: Page, pywire_server):
    page.goto(f"{pywire_server}/form_scenarios")

    page.fill("#comp-user", "bob")
    page.fill("#comp-age", "30")

    # Submit via external button calling child_ref.do_submit()
    page.click("#btn-manual-submit")

    expect(page.locator("#comp-result")).to_have_text("User: bob (Age: 30)")
