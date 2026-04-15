import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    def handle_console(msg):
        print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}")

    page.on("console", handle_console)
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def test_websocket_disconnect_issue_8(page: Page, pywire_server: str):
    page.goto(f"{pywire_server}")
    expect(page.locator("#title")).to_have_text("Hello PyWire")

    # Verify indicator is not visible initially
    # According to Issue #8 and framework convention, it's usually #pywire-connection-status
    # or similar. We will just look for text "Reconnecting" or "Connection lost"
    expect(page.locator("body")).not_to_have_text(
        "Connection lost", use_inner_text=True
    )

    # Easiest way to drop the connection is to close PyWire's internal socket directly
    # This triggers the onclose handler which attempts reconnection and shows the indicator.
    page.evaluate("""
        if (window.pywire && window.pywire.transport && window.pywire.transport.transport && window.pywire.transport.transport.socket) {
            window.pywire.transport.transport.socket.close();
        }
    """)

    # PyWire should show the reconnect overlay (ReconnectOverlay, not StatusOverlay toast)
    expect(page.locator("#_pywire_reconnect_overlay .pw-reconnect-backdrop")).to_be_visible(
        timeout=2000
    )
