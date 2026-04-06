from playwright.sync_api import Page, expect

def test_primitive_reactivity(page: Page, pywire_server):
    page.goto(f"{pywire_server}/binding_reactivity")
    
    expect(page.locator("#count-val")).to_have_text("Count: 0")
    expect(page.locator("#doubled-val")).to_have_text("Doubled: 0")
    
    page.click("#btn-inc")
    expect(page.locator("#count-val")).to_have_text("Count: 1")
    expect(page.locator("#doubled-val")).to_have_text("Doubled: 2")
    
    expect(page.locator("#log li")).to_have_text(["Count changed to: 0", "Count changed to: 1"])

def test_list_reactivity(page: Page, pywire_server):
    page.goto(f"{pywire_server}/binding_reactivity")
    
    expect(page.locator("#list-len")).to_have_text("Length: 1")
    expect(page.locator("#items-list li")).to_have_text(["Initial"])
    
    # NOTE: This will likely fail due to Issue #20 (missing __iter__ reactivity)
    page.click("#btn-add-item")
    expect(page.locator("#list-len")).to_have_text("Length: 2")
    expect(page.locator("#items-list li")).to_have_text(["Initial", "Item 1"])

def test_nested_reactivity(page: Page, pywire_server):
    # NOTE: This will likely fail with Internal Server Error due to Issue #21 (unwrapping)
    page.goto(f"{pywire_server}/binding_reactivity")
    
    expect(page.locator("#user-name")).to_have_text("User: Admin")
    expect(page.locator("#user-role")).to_have_text("Role: Superuser")
    
    page.click("#btn-update-role")
    expect(page.locator("#user-role")).to_have_text("Role: User")
    
    page.click("#btn-update-profile")
    expect(page.locator("#user-name")).to_have_text("User: Updated Admin")

def test_reactivity_reset(page: Page, pywire_server):
    page.goto(f"{pywire_server}/binding_reactivity")
    
    page.click("#btn-inc")
    page.click("#btn-add-item")
    
    # Click reset
    page.click("#btn-reset")
    
    # Give it a moment to update
    page.wait_for_timeout(500)
    
    # Wait for the log to update
    log_items = page.locator("#log li")
    log_items_count = log_items.count()
    log_texts = log_items.all_text_contents()
    print(f"DEBUG: Final log items count: {log_items_count}")
    print(f"DEBUG: Final log items text: {log_texts}")
    
    # The log should definitely HAVE "Count changed to: 0" at the end.
    assert "Count changed to: 0" in log_texts
    assert log_texts[-1] == "Count changed to: 0"
    
    expect(page.locator("#count-val")).to_have_text("Count: 0")
    expect(page.locator("#items-list li")).to_have_text(["Initial"])
