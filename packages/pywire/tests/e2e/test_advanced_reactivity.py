import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_advanced_reactivity_primitives(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")

    expect(page.locator("h1")).to_have_text("Advanced Reactivity")

    # Check initial values
    expect(page.locator("#prim-val")).to_have_text("0")
    expect(page.locator("#lst-len")).to_have_text("3")
    expect(page.locator("#ns-val")).to_have_text("alpha")

    # effect runs once initially or when prim changes, depending on framework specifics.
    # We just ensure it updates when prim updates.
    initial_eff = page.locator("#eff-val").inner_text()

    # Update all
    page.click("#btn-update-all")

    # Check new values
    expect(page.locator("#prim-val")).to_have_text("1")
    expect(page.locator("#lst-len")).to_have_text("4")
    expect(page.locator("#ns-val")).to_have_text("gamma")

    # Check effect triggered
    new_eff = page.locator("#eff-val").inner_text()
    assert initial_eff != new_eff, "Effect did not trigger on primitive update"


def test_form_schema_fields_exposed_ref(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/advanced")

    # Form should have auto-generated fields based on User model (name, age)
    fields = page.locator(".dyn-field")
    expect(fields).to_have_count(2)

    expect(fields.nth(0)).to_have_attribute("data-name", "name")
    expect(fields.nth(1)).to_have_attribute("data-name", "age")

    # They should have inputs with the correct types
    expect(fields.nth(0).locator("input")).to_have_attribute("type", "text")
    expect(fields.nth(1).locator("input")).to_have_attribute("type", "number")
