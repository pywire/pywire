import pytest
from playwright.sync_api import Page, expect

@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")
    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))

def test_basic_reactivity(page: Page, pywire_server: str):
    # Go to the app
    print(f"\nNavigating to {pywire_server}")
    response = page.goto(pywire_server)
    print(f"Response status: {response.status if response else 'No Response'}")
    
    # Debug: Print content if it fails later
    content = page.content()
    print(f"Page content length: {len(content)}")
    if len(content) < 500:
        print(f"Content: {content}")
    
    # Verify initial state
    try:
        expect(page.locator("#title")).to_have_text("Hello PyWire")
        expect(page.locator("#count")).to_have_text("0")
    except Exception as e:
        print(f"\nAssertion failed. Current content: {page.content()}")
        raise e
    
    # Click increment
    page.click("#increment")
    
    # Verify state updated
    expect(page.locator("#count")).to_have_text("1")
    
    # Click again
    page.click("#increment")
    expect(page.locator("#count")).to_have_text("2")

def test_page_reload(page: Page, pywire_server: str):
    page.goto(pywire_server)
    expect(page.locator("#count")).to_have_text("0")
    
    page.click("#increment")
    expect(page.locator("#count")).to_have_text("1")
    
    # Reload page
    page.reload()
    
    expect(page.locator("#count")).to_have_text("0")

def test_input_binding(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/input_binding")
    
    # Verify initial state
    expect(page.locator("#title")).to_have_text("Input Binding")
    expect(page.locator("#name-display")).to_have_text("Hello, Hello!")
    expect(page.locator("#name-input")).to_have_value("Hello")
    
    # Type into the input
    page.fill("#name-input", "Playwright")
    
    # Wait for the text node to update (two-way binding via @input)
    # Actually input_binding.wire uses @submit.prevent={update_text}
    # So we need to click Submit
    page.click("#native-submit")
    
    print(f"DEBUG: name-display text: '{page.locator('#name-display').text_content()}'")
    expect(page.locator("#name-display")).to_have_text("Hello, Playwright!")

def test_structural_directives(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/structural")
    expect(page.locator("#structural-title")).to_have_text("Structural Directives Test")
    
    # $if and $show are true initially
    expect(page.locator("#if-element")).to_be_visible()
    expect(page.locator("#show-element")).to_be_visible()
    
    # Initial list has 2 items
    expect(page.locator(".list-item")).to_have_count(2)
    
    # Toggle visibility
    page.click("#btn-toggle")
    
    # $if removes from DOM
    expect(page.locator("#if-element")).to_have_count(0)
    # $show just hides
    expect(page.locator("#show-element")).to_have_count(1)
    expect(page.locator("#show-element")).to_be_hidden()
    
    # Add item
    page.click("#btn-add")
    expect(page.locator(".list-item")).to_have_count(3)
    # Verify the new item is "Cherry"
    expect(page.locator(".list-item").nth(2)).to_have_text("Cherry")

def test_persistent_elements(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}/persistent")
    expect(page.locator("#persistent-title")).to_have_text("Persistent Elements Test")
    
    # Assert initial state
    expect(page.locator("#persistent-input")).to_have_value("will-be-overwritten")
    
    # Type into the persistent input exactly as a user would
    page.fill("#persistent-input", "User typed data")
    
    # Wait to ensure it's filled
    expect(page.locator("#persistent-input")).to_have_value("User typed data")
    
    # Add a custom marker to the DOM element to verify identity matching morphdom
    page.evaluate("document.getElementById('persistent-input').__test_marker = true")
    
    # Trigger a server rerender by clicking the button
    page.click("#btn-click")
    expect(page.locator("#click-count")).to_have_text("Clicks: 1")
    
    # Assert that the input still contains the user's typed data
    # (Morphdom preserved it because of $permanent attribute)
    expect(page.locator("#persistent-input")).to_have_value("User typed data")
    
    # Assert the exact same DOM node still exists
    marker_exists = page.evaluate("document.getElementById('persistent-input').__test_marker")
    assert marker_exists is True, "The persistent DOM node was replaced by Morphdom!"
