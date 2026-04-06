from playwright.sync_api import Page, expect

def test_special_characters(page: Page, pywire_server):
    page.goto(f"{pywire_server}/special_chars")
    
    # Verify that the literal tokens are present in the DOM text
    # (The browser should escape these if they are within P tags)
    expect(page.locator("#p1")).to_have_text("Closing body: </body>")
    expect(page.locator("#p2")).to_have_text("Closing html: </html>")
    expect(page.locator("#p3")).to_have_text("Both: </body> and </html>")
    
    # Ensure the assertion in conftest.py (assert_no_nested_html_body) 
    # doesn't trip up on these strings being present if they were somehow
    # mis-parsed.
