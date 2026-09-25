"""Optimistic UI e2e under 500 ms artificial latency (review focus #8).

Pins, in a real browser against the stateless transport:
- the predicted class + double-submit guard apply SYNCHRONOUSLY on click (<50ms)
- an accepted prediction survives the morph with no flicker (node identity
  stable, class never disappears between click and settle)
- a rejected prediction is auto-reverted by the arriving patch
- a rapid double-click invokes the handler exactly once

The fixture page (`optimistic.wire`) accepts every odd-numbered handler call
and rejects every even one (server state then contradicts the prediction).
"""

import time

import pytest
from playwright.sync_api import Page, expect

# Click + measure, all in one synchronous in-page tick: the optimistic apply
# runs inside the click dispatch, so `dt` bounds how long the prediction took.
_CLICK_AND_MEASURE = """() => {
  const btn = document.getElementById('toggle');
  const t0 = performance.now();
  btn.click();
  return {
    dt: performance.now() - t0,
    hasClass: btn.classList.contains('done'),
    disabled: btn.disabled,
    pending: btn.hasAttribute('data-pw-pending'),
  };
}"""


@pytest.fixture(autouse=True)
def capture_console(page: Page):
    page.on("console", lambda msg: print(f"\n[BROWSER CONSOLE] {msg.type}: {msg.text}"))
    page.on("pageerror", lambda exc: print(f"\n[BROWSER ERROR] {exc}"))


@pytest.fixture()
def slow_stateless(page: Page):
    """Add 500 ms of latency to every stateless event POST."""

    def _delay(route):
        time.sleep(0.5)
        route.continue_()

    page.route("**/_pywire/stateless", _delay)


def _goto(page: Page, server: str) -> None:
    page.goto(f"{server}/optimistic")
    expect(page.locator("#calls")).to_have_text("0")


def test_prediction_applied_synchronously_and_guards_in_flight(
    page: Page, stateless_server: str, slow_stateless
):
    _goto(page, stateless_server)

    result = page.evaluate(_CLICK_AND_MEASURE)
    assert result["dt"] < 50, (
        f"prediction took {result['dt']:.2f}ms after click — must be "
        "synchronous (<50ms) while the request is still in flight"
    )
    assert result["hasClass"], "predicted 'done' class missing right after click"
    assert result["disabled"], "button not disabled right after click"
    assert result["pending"], "data-pw-pending marker missing right after click"

    # Still guarded while the 500 ms request is in flight...
    assert page.locator("#toggle").is_disabled(), "button re-enabled mid-flight"
    # ...and released once the response lands (call 1 is accepted).
    expect(page.locator("#toggle")).to_be_enabled(timeout=5000)
    expect(page.locator("#calls")).to_have_text("1")


def test_accepted_prediction_survives_patch_without_flicker(
    page: Page, stateless_server: str, slow_stateless
):
    _goto(page, stateless_server)

    # Install a flicker watcher + node-identity anchor, then click — all in one
    # tick. Any mutation between click and settle that finds the class missing
    # (or the button replaced) is a flicker.
    page.evaluate(
        """() => {
      const btn = document.getElementById('toggle');
      window.__btn = btn;
      window.__flicker = 0;
      new MutationObserver(() => {
        const el = document.getElementById('toggle');
        if (!el || !el.classList.contains('done')) window.__flicker++;
      }).observe(document.documentElement, {
        subtree: true, attributes: true, childList: true, characterData: true,
      });
      btn.click();
      if (!btn.classList.contains('done')) window.__flicker++;
    }"""
    )

    # Settle: the accepted call renders calls=1 and class="done" server-side.
    expect(page.locator("#calls")).to_have_text("1", timeout=5000)
    expect(page.locator("#toggle")).to_be_enabled()

    result = page.evaluate(
        """() => {
      const el = document.getElementById('toggle');
      return {
        sameNode: el.isSameNode(window.__btn),
        flicker: window.__flicker,
        hasClass: el.classList.contains('done'),
        pending: el.hasAttribute('data-pw-pending'),
      };
    }"""
    )
    assert result["sameNode"], "morph replaced the button node (identity lost)"
    assert result["flicker"] == 0, (
        f"predicted class disappeared {result['flicker']} time(s) between "
        "click and settle"
    )
    assert result["hasClass"], "accepted prediction did not survive the patch"
    assert not result["pending"], "pending marker not cleared by the patch"


def test_rejected_prediction_auto_reverts(
    page: Page, stateless_server: str, slow_stateless
):
    _goto(page, stateless_server)

    # Click 1 (odd call): accepted → server state has done=True.
    page.click("#toggle")
    expect(page.locator("#calls")).to_have_text("1", timeout=5000)
    expect(page.locator("#toggle")).to_be_enabled()
    assert page.locator("#toggle").evaluate("el => el.classList.contains('done')")

    # Click 2 (even call): handler rejects — server renders WITHOUT the class
    # while the client-side prediction still claims it. The arriving patch must
    # strip it (auto-revert) and release the guard.
    result = page.evaluate(_CLICK_AND_MEASURE)
    assert result["hasClass"], "prediction not applied for the rejected click"
    assert result["pending"], "pending marker not applied for the rejected click"
    assert result["disabled"], "button not guarded for the rejected click"

    expect(page.locator("#calls")).to_have_text("2", timeout=5000)
    expect(page.locator("#toggle")).to_be_enabled()

    result = page.evaluate(
        """() => {
      const el = document.getElementById('toggle');
      return {
        hasClass: el.classList.contains('done'),
        pending: el.hasAttribute('data-pw-pending'),
        disabled: el.disabled,
      };
    }"""
    )
    assert not result["hasClass"], "rejected prediction survived the patch"
    assert not result["pending"], "pending marker survived the patch"
    assert not result["disabled"], "button left disabled after rejection"


def test_rapid_double_click_submits_once(
    page: Page, stateless_server: str, slow_stateless
):
    _goto(page, stateless_server)

    # Two clicks in the same tick: the first applies the guard (disabled +
    # pending), so the second must never reach the server.
    page.evaluate(
        """() => {
      const btn = document.getElementById('toggle');
      btn.click();
      btn.click();
    }"""
    )

    # Handler invocation count is rendered in the page state.
    expect(page.locator("#calls")).to_have_text("1", timeout=5000)
    expect(page.locator("#toggle")).to_be_enabled()
    page.wait_for_timeout(700)  # longer than the 500ms route delay

    posts = page.evaluate(
        "performance.getEntriesByType('resource')"
        ".filter(r => r.name.includes('/_pywire/stateless')).length"
    )
    assert posts == 1, f"expected exactly one stateless POST, saw {posts}"
