import logging

from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)

# Confirmed live against purchase.filmlinc.org (Tessitura TNEW) by loading
# the real login page - see README's "Known limitations" for what's
# confirmed vs. guessed below this point.
LOGIN_URL = "https://purchase.filmlinc.org/account/login"
USERNAME_SELECTOR = "#PatronAccountLogin_Username"
PASSWORD_SELECTOR = "#PatronAccountLogin_Password"
LOGIN_BUTTON_SELECTOR = "#tn-login-button"


class CheckoutError(Exception):
    pass


def _launch_browser(p):
    launch_args = {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]}
    try:
        return p.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        logger.info("real Chrome channel unavailable, falling back to bundled Chromium")
        return p.chromium.launch(**launch_args)


def attempt_purchase(quantity):
    """Best-effort automated purchase the moment a showtime opens up.

    IMPORTANT - read this before trusting it: only the login step has been
    verified against the real site, and in that verification the login POST
    itself was intercepted by the site's Imperva Incapsula WAF ("Request
    unsuccessful" challenge page) rather than reaching the real login
    response. Everything past login (ticket type/quantity selection, add
    to cart, checkout, payment) is written against Tessitura TNEW's common
    class-naming conventions, not a confirmed DOM - the buy widget never
    rendered in testing even on a genuinely-available screening, possibly
    because Queue-it's "safetynet" token gates it for automated clients.
    This may simply fail every time it's tried; that's why main.py always
    sends an alert first regardless of what this returns.

    Returns (success: bool, message: str).
    """
    if not config.FLC_EMAIL or not config.FLC_PASSWORD:
        return False, "PTA_FLC_EMAIL / PTA_FLC_PASSWORD not set - can't log in"

    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()

        try:
            page.goto(LOGIN_URL, timeout=30000, wait_until="networkidle")
            page.fill(USERNAME_SELECTOR, config.FLC_EMAIL)
            page.fill(PASSWORD_SELECTOR, config.FLC_PASSWORD)
            with page.expect_navigation(timeout=15000):
                page.click(LOGIN_BUTTON_SELECTOR)
            page.wait_for_timeout(1500)

            html = page.content()
            if "incapsula incident" in html.lower() or "request unsuccessful" in html.lower():
                return False, "login blocked by Incapsula WAF challenge"
            if "PatronAccountLogin_Username" in html:
                return False, "still on login page after submit - credentials rejected or blocked"

            page.goto(config.PURCHASE_URL, timeout=30000, wait_until="networkidle")

            sold_out_text = page.locator(
                "text=Tickets to the screening you have selected are no longer available"
            )
            unavailable_banner = page.locator(".tn-event-detail__unavailable-text")
            if sold_out_text.count() or unavailable_banner.count():
                return False, "purchase page still shows sold-out/standby - opening already gone"

            # TODO (unverified - the buy widget never rendered in testing):
            # select ticket type/quantity and add to cart. Update these
            # selectors from a real observed DOM once a screening is
            # actually available and this can be watched live, per the
            # dry-run-first philosophy in resy-sniper's README.
            qty_selector = page.locator("select[name*='quantity' i], select[id*='quantity' i]")
            if qty_selector.count() == 0:
                return False, (
                    "no quantity selector found on purchase page - buy widget didn't render "
                    "(see README: Queue-it may be gating it for automated clients)"
                )
            qty_selector.first.select_option(str(min(quantity, 2)))

            add_to_cart = page.locator(
                "button:has-text('Add to Cart'), button:has-text('Buy'), "
                "button:has-text('Add To Cart')"
            )
            if add_to_cart.count() == 0:
                return False, "no add-to-cart button found after selecting quantity"
            add_to_cart.first.click()
            page.wait_for_timeout(2000)

            checkout_button = page.locator(
                "a:has-text('Checkout'), button:has-text('Checkout'), "
                "a:has-text('Proceed to Checkout')"
            )
            if checkout_button.count() == 0:
                return False, "added to cart but no checkout button found"
            checkout_button.first.click()
            page.wait_for_timeout(2000)

            place_order = page.locator(
                "button:has-text('Place Order'), button:has-text('Submit Order'), "
                "button:has-text('Complete Order'), button:has-text('Purchase')"
            )
            if place_order.count() == 0:
                return False, (
                    "reached checkout but no place-order button found - likely needs a "
                    "saved payment method selected first (unverified flow, see README)"
                )
            place_order.first.click()
            page.wait_for_timeout(3000)

            confirmation = page.locator("text=/order confirm|thank you|order number/i")
            if confirmation.count() == 0:
                return False, "clicked place order but no confirmation text found - outcome unclear"

            return True, "purchase appears to have completed - verify manually via confirmation"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            browser.close()
