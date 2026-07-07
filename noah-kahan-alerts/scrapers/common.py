import re

from playwright.sync_api import sync_playwright

import config

PRICE_RE = re.compile(r"\$([0-9]{1,4}(?:,[0-9]{3})*)(?:\.[0-9]{2})?")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_rendered_text(url, timeout_ms=30000):
    """Render `url` in headless Chromium and return the page's visible text.

    These sites run bot detection (see README) - this can fail or start
    returning junk at any time and may need real-world tuning.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            text = page.inner_text("body")
        finally:
            browser.close()
    return text


NON_TICKET_LINE_RE = re.compile(
    r"parking|fee|delivery|shipping|donation|merch|vip package|add-?on",
    re.I,
)


def lowest_sane_price(text):
    """Cheapest $ amount in `text` that looks like a plausible ticket price.

    Crude but dependency-free: drops lines that look like parking/fees/other
    non-ticket line items, then filters remaining $ amounts using
    config.MIN_SANE_TICKET_PRICE / MAX_SANE_TICKET_PRICE.
    """
    ticket_lines = [
        line for line in text.splitlines() if not NON_TICKET_LINE_RE.search(line)
    ]
    prices = [
        float(p.replace(",", ""))
        for line in ticket_lines
        for p in PRICE_RE.findall(line)
    ]
    plausible = [
        p for p in prices
        if config.MIN_SANE_TICKET_PRICE <= p <= config.MAX_SANE_TICKET_PRICE
    ]
    return min(plausible) if plausible else None
