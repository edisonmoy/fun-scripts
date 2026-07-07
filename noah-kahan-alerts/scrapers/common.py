import random
import re
import time

from playwright.sync_api import sync_playwright

import config

PRICE_RE = re.compile(r"\$([0-9]{1,4}(?:,[0-9]{3})*)(?:\.[0-9]{2})?")
NON_TICKET_LINE_RE = re.compile(
    r"parking|fee|delivery|shipping|donation|merch|vip package|add-?on",
    re.I,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Very small stealth pass: hides the most common automation tells that
# basic bot-detection checks for. Not a guarantee against Akamai/PerimeterX
# grade detection, just removes the free giveaways.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
"""

BLOCK_TEXT_MARKERS = [
    "pardon the interruption",
    "access denied",
    "just a moment",
    "verify you are a human",
    "px-captcha",
    "cf-challenge",
    "attention required",
    "unusual traffic",
    "are you a robot",
]


class FetchResult:
    """Outcome of one scrape attempt.

    status is one of "ok" (page loaded, not blocked), "blocked" (bot
    detection caught us), or "error" (navigation/timeout/other exception).
    `captured` holds any JSON response bodies whose URL matched the
    caller's API pattern - this is the primary data source. `text` is the
    rendered page's visible text, used only as a fallback.
    """

    def __init__(self, status, http_status=None, captured=None, text="", diagnostic=""):
        self.status = status
        self.http_status = http_status
        self.captured = captured or []
        self.text = text
        self.diagnostic = diagnostic


def _looks_blocked(http_status, text):
    if http_status in (403, 429, 503):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in BLOCK_TEXT_MARKERS)


def fetch_with_capture(url, api_url_pattern, retries=3, timeout_ms=30000):
    """Load `url` in a stealth-ish headless browser, capturing any JSON
    network responses whose URL matches `api_url_pattern` (a compiled
    regex). Retries with jittered backoff, and classifies the outcome so
    callers can decide whether to alert/escalate.
    """
    last_result = FetchResult("error", diagnostic="no attempts made")

    for attempt in range(1, retries + 1):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1366, "height": 900},
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                context.add_init_script(STEALTH_INIT_SCRIPT)
                page = context.new_page()

                captured = []

                def on_response(response, _captured=captured):
                    try:
                        content_type = response.headers.get("content-type", "")
                        if api_url_pattern.search(response.url) and "json" in content_type:
                            _captured.append(response.json())
                    except Exception:
                        pass  # not every matched response is parseable JSON; skip it

                page.on("response", on_response)

                time.sleep(random.uniform(0.5, 2.0))  # avoid an instant, robotic navigation
                resp = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
                http_status = resp.status if resp else None
                text = page.inner_text("body")
                browser.close()

            if _looks_blocked(http_status, text):
                last_result = FetchResult(
                    "blocked", http_status=http_status, text=text, diagnostic=text[:2000]
                )
            else:
                return FetchResult(
                    "ok", http_status=http_status, captured=captured, text=text
                )
        except Exception as exc:
            last_result = FetchResult("error", diagnostic=f"{type(exc).__name__}: {exc}")

        if attempt < retries:
            time.sleep(2 ** attempt + random.uniform(0, 1))

    return last_result


def lowest_sane_price(text):
    """Cheapest $ amount in `text` that looks like a plausible ticket price.

    Crude fallback for when network-JSON capture finds nothing usable:
    drops lines that look like parking/fees/other non-ticket line items,
    then filters remaining $ amounts using config.MIN_SANE_TICKET_PRICE /
    MAX_SANE_TICKET_PRICE.
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


PRICE_KEY_RE = re.compile(r"(price|amount|total)$", re.I)
QUANTITY_KEY_RE = re.compile(r"(quantity|qty)$", re.I)
SECTION_KEY_RE = re.compile(r"section", re.I)
ROW_KEY_RE = re.compile(r"^row", re.I)


def _numeric(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, dict):
        for key in ("amount", "value", "total"):
            if key in value:
                return _numeric(value[key])
    return None


def extract_listings(payload, _out=None):
    """Best-effort, schema-agnostic scan of a captured JSON blob for
    listing-shaped dicts: anything with both a price-like and a
    quantity-like field, anywhere in the tree.

    This is intentionally schema-agnostic - the real StubHub/Vivid Seats
    API shapes weren't observable while building this (see README), so
    hardcoding exact key paths would just be guessing. Tighten this to the
    real keys once a real payload has been seen (e.g. via an escalated
    diagnostic snippet).
    """
    if _out is None:
        _out = []

    if isinstance(payload, dict):
        price_val = qty_val = section_val = row_val = None
        for key, value in payload.items():
            if PRICE_KEY_RE.search(key) and price_val is None:
                price_val = _numeric(value)
            elif QUANTITY_KEY_RE.search(key) and isinstance(value, (int, float)):
                qty_val = int(value)
            elif SECTION_KEY_RE.search(key) and isinstance(value, str):
                section_val = value
            elif ROW_KEY_RE.search(key) and isinstance(value, str):
                row_val = value

        if price_val is not None and qty_val is not None:
            _out.append(
                {
                    "price_per_ticket": price_val,
                    "quantity": qty_val,
                    "section": section_val,
                    "row": row_val,
                }
            )

        for value in payload.values():
            extract_listings(value, _out)
    elif isinstance(payload, list):
        for item in payload:
            extract_listings(item, _out)

    return _out


def lowest_pair_price(listings):
    """Cheapest listing with at least 2 tickets available together."""
    pairs = [ln for ln in listings if ln["quantity"] >= 2]
    if not pairs:
        return None
    return min(pairs, key=lambda ln: ln["price_per_ticket"])


def check_price(url, api_url_pattern):
    """Full pipeline for one site: capture network JSON, extract a real
    2-together price if possible, otherwise fall back to the crude text
    heuristic. Returns a dict describing the outcome and confidence.
    """
    result = fetch_with_capture(url, api_url_pattern)

    if result.status in ("blocked", "error"):
        return {
            "price_per_ticket": None,
            "status": result.status,
            "confidence": None,
            "diagnostic": result.diagnostic,
        }

    listings = []
    for payload in result.captured:
        listings.extend(extract_listings(payload))

    best = lowest_pair_price(listings)
    if best:
        return {
            "price_per_ticket": best["price_per_ticket"],
            "section": best.get("section"),
            "row": best.get("row"),
            "status": "ok",
            "confidence": "high",
            "diagnostic": "",
        }

    fallback_price = lowest_sane_price(result.text)
    return {
        "price_per_ticket": fallback_price,
        "status": "fallback" if fallback_price is not None else "error",
        "confidence": "low",
        "diagnostic": "" if fallback_price is not None else "no price found in fallback text",
    }
