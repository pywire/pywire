"""Task 13 e2e: keyed {$for} regions over the WS transport.

Toggling row 500 of a 1000-row keyed list must confine every DOM mutation
to that row's wrapper (MutationObserver), leave sibling rows 499/501 as the
SAME node objects (isSameNode), and a structural append must still
full-loop-patch correctly (row 1001 appears).
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    page.on("console", lambda m: print(f"\n[BROWSER CONSOLE] {m.type}: {m.text}"))
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


def _goto_ready(page: Page, url: str):
    page.goto(url)
    page.wait_for_timeout(500)  # let the WS connect (pattern from other e2e)
    expect(page.locator("#rows > div[data-pw-region]")).to_have_count(
        1000, timeout=15_000
    )


def test_keyed_toggle_confined_to_row(page: Page, keyed_list_server: str):
    _goto_ready(page, keyed_list_server)
    expect(page.locator('[data-pw-region$="#500"] .done')).to_have_text("False")

    page.evaluate(
        """() => {
        window.__muts = [];
        window.__obs = new MutationObserver(rs => {
            for (const r of rs) {
                const t = r.target;
                const el = t.nodeType === Node.ELEMENT_NODE ? t : t.parentElement;
                const w = el ? el.closest('[data-pw-region]') : null;
                window.__muts.push(w ? w.getAttribute('data-pw-region') : 'ORPHAN');
            }
        });
        window.__obs.observe(document.getElementById('rows'), {
            subtree: true, childList: true, attributes: true, characterData: true,
        });
        window.__r499 = document.querySelector('[data-pw-region$="#499"]');
        window.__r501 = document.querySelector('[data-pw-region$="#501"]');
        window.__ul = document.getElementById('rows');
    }"""
    )

    page.locator('[data-pw-region$="#500"] button').click()
    expect(page.locator('[data-pw-region$="#500"] .done')).to_have_text(
        "True", timeout=10_000
    )

    res = page.evaluate(
        """() => ({
        muts: window.__muts,
        same499: window.__r499.isSameNode(document.querySelector('[data-pw-region$="#499"]')),
        same501: window.__r501.isSameNode(document.querySelector('[data-pw-region$="#501"]')),
        sameUl: window.__ul.isSameNode(document.getElementById('rows')),
    })"""
    )
    assert res["muts"], "observer saw no mutations at all"
    assert all(m.endswith("#500") for m in res["muts"]), (
        f"mutations escaped row 500: {[m for m in res['muts'] if not m.endswith('#500')]}"
    )
    assert res["same499"], "row 499 wrapper was replaced"
    assert res["same501"], "row 501 wrapper was replaced"
    assert res["sameUl"], "the <ul> itself was replaced"


def test_keyed_structural_append(page: Page, keyed_list_server: str):
    _goto_ready(page, keyed_list_server)
    page.click("#add")
    expect(page.locator("#rows > div[data-pw-region]")).to_have_count(
        1001, timeout=10_000
    )
    expect(page.locator('[data-pw-region$="#1000"] .name')).to_have_text("new-row")
    expect(page.locator('[data-pw-region$="#1000"] li')).to_be_visible()
