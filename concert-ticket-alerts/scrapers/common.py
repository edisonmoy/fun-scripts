import json
import logging
import random
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(r"\$([0-9]{1,4}(?:,[0-9]{3})*)(?:\.[0-9]{2})?")
NON_TICKET_LINE_RE = re.compile(
    r"parking|fee|delivery|shipping|donation|merch|vip package|add-?on",
    re.I,
)
# A line like "$390 - $3,052+" is a price-range summary stat (often a
# filter bar showing the site-wide min/max regardless of the current
# quantity filter), not an individual listing - it should never win
# "lowest price" over an actual listing.
PRICE_RANGE_LINE_RE = re.compile(r"\$[\d,]+\s*-\s*\$[\d,]+")

# Deliberately NOT overriding user_agent: a hardcoded UA string that
# doesn't match the browser's real Client Hints headers / TLS fingerprint
# is itself a bot-detection signal (inconsistent fingerprint surfaces are
# more suspicious than a consistent, honestly-reported one). Let whichever
# browser we launch self-report natively across every surface instead.

# Very small stealth pass: hides the most common automation tells that
# basic bot-detection checks for. Not a guarantee against Akamai/PerimeterX
# grade detection, just removes the free giveaways.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
"""


def _launch_browser(p):
    """Prefer a real installed Chrome binary over Playwright's bundled
    Chromium - GitHub Actions' ubuntu-latest runners ship Chrome stable by
    default, and a real Chrome's TLS/JA3 fingerprint and Client Hints are
    more convincing to bot detection than the bundled build's. Falls back
    to bundled Chromium wherever real Chrome isn't installed (e.g. local
    dev, other runner images).
    """
    launch_args = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return p.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        logger.info("real Chrome channel unavailable, falling back to bundled Chromium")
        return p.chromium.launch(**launch_args)

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

# Many SEO-conscious sites (Next.js etc.) server-render their full listing
# dataset directly into the HTML as a JSON blob, rather than fetching it via
# a separate XHR/fetch call after load. A network-response listener never
# sees that data at all - these patterns pull it straight out of the HTML.
EMBEDDED_JSON_PATTERNS = [
    re.compile(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S),
    re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.*?\});", re.S),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.S),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});", re.S),
]


def extract_embedded_json_blobs(html):
    """Best-effort scan of raw page HTML for SSR-embedded JSON. Regex over
    HTML/JS is inherently fragile (can't handle a literal '};' inside a
    string value, for instance) but is a reasonable tradeoff here - a
    missed blob just means falling through to network capture or the text
    heuristic, not a wrong answer.
    """
    blobs = []
    for pattern in EMBEDDED_JSON_PATTERNS:
        for match in pattern.findall(html):
            try:
                blobs.append(json.loads(match))
            except json.JSONDecodeError:
                continue
    return blobs


SCRIPT_ID_RE = re.compile(r'<script[^>]*\bid=["\']([^"\']+)["\']', re.I)


def find_script_ids(html):
    """Distinct script tag ids present on the page - diagnostic aid for
    finding the real SSR-embedded-JSON id when EMBEDDED_JSON_PATTERNS
    doesn't match anything (e.g. the site uses a different variable name
    than __NEXT_DATA__/__INITIAL_STATE__/__APOLLO_STATE__).
    """
    return sorted(set(SCRIPT_ID_RE.findall(html)))


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
        logger.info("attempt %d/%d: fetching %s", attempt, retries, url)
        try:
            with sync_playwright() as p:
                browser = _launch_browser(p)
                context = browser.new_context(
                    viewport={"width": 1366, "height": 900},
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                context.add_init_script(STEALTH_INIT_SCRIPT)
                page = context.new_page()

                captured = []
                all_response_urls = []

                def on_response(response, _captured=captured, _all_urls=all_response_urls):
                    if len(_all_urls) < 40:
                        _all_urls.append(response.url)
                    try:
                        content_type = response.headers.get("content-type", "")
                        if api_url_pattern.search(response.url) and "json" in content_type:
                            _captured.append(response.json())
                    except Exception:
                        pass  # not every matched response is parseable JSON; skip it

                page.on("response", on_response)

                if attempt == 1:
                    # Warm up with a homepage visit first, so the deep-link
                    # event page is reached via a natural referrer/cookie
                    # chain instead of a bare cold hit - real visitors
                    # essentially never teleport straight to a deep link.
                    # Best-effort: if this fails for any reason, proceed
                    # straight to the real target anyway.
                    try:
                        origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
                        page.goto(origin, timeout=10000, wait_until="domcontentloaded")
                        time.sleep(random.uniform(1.0, 2.5))
                    except Exception:
                        pass

                time.sleep(random.uniform(0.5, 2.0))  # avoid an instant, robotic navigation
                resp = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                http_status = resp.status if resp else None
                try:
                    # Give async listing/price requests time to fire and be
                    # captured. Some sites (persistent polling, analytics
                    # beacons) never go fully idle, so this is a bounded
                    # grace period, not a hard requirement like networkidle
                    # was - that caused every Vivid Seats attempt to burn
                    # the full 30s timeout and fail outright.
                    page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    logger.info("page never went fully idle, proceeding with what was captured")
                text = page.inner_text("body")
                html = page.content()
                browser.close()

            if _looks_blocked(http_status, text):
                logger.warning(
                    "attempt %d/%d: blocked (http_status=%s)", attempt, retries, http_status
                )
                last_result = FetchResult(
                    "blocked", http_status=http_status, text=text, diagnostic=text[:2000]
                )
            else:
                embedded = extract_embedded_json_blobs(html)
                network_json_count = len(captured)
                captured.extend(embedded)

                diagnostic = ""
                if network_json_count == 0 and not embedded:
                    # Nothing structured found at all - leave a breadcrumb
                    # instead of guessing blind next time: what script tag
                    # ids and response URLs actually exist on this page.
                    script_ids = find_script_ids(html)
                    diagnostic = (
                        f"no network JSON matched api_url_pattern; no embedded JSON blobs "
                        f"matched known patterns; script tag ids on page: {script_ids[:20]}; "
                        f"sample response URLs: {all_response_urls[:20]}"
                    )

                logger.info(
                    "attempt %d/%d: ok (http_status=%s, %d network JSON + %d embedded JSON)",
                    attempt, retries, http_status, network_json_count, len(embedded),
                )
                return FetchResult(
                    "ok", http_status=http_status, captured=captured, text=text,
                    diagnostic=diagnostic,
                )
        except Exception as exc:
            logger.warning(
                "attempt %d/%d: raised %s: %s", attempt, retries, type(exc).__name__, exc
            )
            last_result = FetchResult("error", diagnostic=f"{type(exc).__name__}: {exc}")

        if attempt < retries:
            delay = 2 ** attempt + random.uniform(0, 1)
            logger.info("retrying in %.1fs", delay)
            time.sleep(delay)

    return last_result


def lowest_sane_price(text):
    """Cheapest $ amount in `text` that looks like a plausible ticket price.

    Crude fallback for when network-JSON capture finds nothing usable:
    drops lines that look like parking/fees/other non-ticket line items or
    a price-range summary stat, then filters remaining $ amounts using
    config.MIN_SANE_TICKET_PRICE / MAX_SANE_TICKET_PRICE.
    """
    ticket_lines = [
        line for line in text.splitlines()
        if not NON_TICKET_LINE_RE.search(line) and not PRICE_RANGE_LINE_RE.search(line)
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


def _extract_vividseats_ticket(payload):
    """Vivid Seats' real individual-listing schema, from payload["tickets"]
    in its captured internal API response. Confirmed against real captured
    data: {"s": "Promenade Reserved 527", "r": "15", "q": "1",
    "p": "294.50", "i": "VB16030960293", "aip": "397.46", ...} - "q" is
    quantity in that specific listing, "s" is section, "r" is row, "i" is
    a real alphanumeric listing id.

    Price: use "aip" (all-in price), not "p". A live cross-check caught
    this - our alert for section "Promenade Reserved 528" row "9" said
    $444, the live site's *same listing* (confirmed by matching section+
    row, "Lowest Price in Section" badge) showed $599 labeled "Fees
    Incl.". $599/$444 = 1.349, matching the aip/p ratio in the original
    sample data (397.46/294.50 = 1.350) almost exactly - "p" is the base
    price before fees, "aip" is what the site actually displays and what
    a buyer actually pays. Falls back to "p" if "aip" is missing/
    unparseable, still better than nothing.

    Distinguished from payload["groups"] (a *different*, superficially
    similar "l"/"h"/"q" price-range-per-section schema this project
    previously mistook for individual listings - see the removed
    _extract_vividseats_listing below): groups has no row field and its
    "q" means "count of listings in this section", not a purchasable
    quantity. Requiring p+q+r+s together as a fingerprint is specific
    enough to avoid both that shape and unrelated JSON.
    """
    if not ({"p", "q", "r", "s"} <= payload.keys()):
        return None
    try:
        quantity = int(payload["q"])
        section = payload.get("s")
        row = payload.get("r")
    except (TypeError, ValueError):
        return None

    try:
        price = float(payload["aip"])
    except (KeyError, TypeError, ValueError):
        try:
            price = float(payload["p"])
        except (TypeError, ValueError):
            return None

    return {
        "price_per_ticket": price,
        "quantity": quantity,
        "section": section,
        "row": row,
    }


def extract_listings(payload, _out=None):
    """Best-effort, schema-agnostic scan of a captured JSON blob for
    listing-shaped dicts: anything with both a price-like and a
    quantity-like field, anywhere in the tree.

    This is intentionally schema-agnostic - the real StubHub API shape
    wasn't observable while building this (see README), so hardcoding
    exact key paths would just be guessing. Tighten this to the real keys
    once a real payload has been seen (e.g. via an escalated diagnostic
    snippet). Vivid Seats' real schema *was* observed (see
    _extract_vividseats_ticket above) and is checked first.

    NOTE: an earlier version of this function special-cased a *different*
    Vivid Seats payload shape with keys "l"/"q"/"productionId" as price/
    quantity/event id (from payload["groups"], not payload["tickets"]).
    That was wrong - the "l"/"h" fields with "si"/"li"/"pi" (seller/
    listing/product id) left blank and geometric fields (ang, dst, rx, ry,
    s3d, p3d) turned out to be seat-map heatmap/visualization data (a price
    *range* per map zone), not individual bookable listings, and it was
    silently returning a wrong price at fake "high" confidence - worse
    than the honest low-confidence fallback it replaced. Removed in favor
    of the real per-listing schema above, found via
    summarize_captured_payloads()'s semantically-named-field search.
    """
    if _out is None:
        _out = []

    if isinstance(payload, dict):
        vividseats_ticket = _extract_vividseats_ticket(payload)
        if vividseats_ticket:
            _out.append(vividseats_ticket)

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


def _find_lists(payload, out):
    """Recursively collect every list found anywhere in payload's tree -
    real API responses often nest the actual data a level or two deep
    (e.g. payload["data"]["ticketGroups"]), same as extract_listings
    already has to handle.
    """
    if isinstance(payload, dict):
        for value in payload.values():
            _find_lists(value, out)
    elif isinstance(payload, list):
        out.append(payload)
        for item in payload:
            _find_lists(item, out)


LISTING_LIKE_KEY_RE = re.compile(r"ticket|listing|offer|inventory|^groups$", re.I)


def _find_named_lists(payload, path, out):
    """Recursively find list-valued fields whose *key name* suggests it's
    the actual per-listing feed (tickets/listings/offers/groups), with the
    dotted path it was found at. "biggest list anywhere" alone can grab
    the wrong thing - e.g. a large seat-map heatmap/visualization array
    that happens to outsize the real (smaller) listings array. A
    semantically-named field is a much stronger signal of relevance than
    raw size.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            new_path = f"{path}.{key}" if path else key
            if isinstance(value, list) and LISTING_LIKE_KEY_RE.search(key):
                out.append((new_path, value))
            _find_named_lists(value, new_path, out)
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _find_named_lists(item, f"{path}[{i}]", out)


def summarize_captured_payloads(captured):
    """Diagnostic summary of every captured JSON payload: top-level shape,
    any semantically-named listing-like fields (tickets/listings/offers/
    groups) found anywhere with a sample item, and the single biggest list
    found anywhere as a fallback. A payload can look empty (e.g. pagination
    metadata with `"listings": []`) while the real data sits in a
    different captured response or nested deeper - dumping just the first
    payload's top level missed that, and picking purely by size can grab
    an unrelated large array (see extract_listings' docstring for how that
    went wrong once already).
    """
    summaries = []
    biggest_list = []
    named_lists = []

    for i, payload in enumerate(captured):
        if isinstance(payload, dict):
            summaries.append(f"payload[{i}] dict keys={list(payload.keys())[:10]}")
        elif isinstance(payload, list):
            summaries.append(f"payload[{i}] list len={len(payload)}")
        else:
            summaries.append(f"payload[{i}] {type(payload).__name__}")

        found = []
        _find_lists(payload, found)
        for lst in found:
            if len(lst) > len(biggest_list):
                biggest_list = lst

        _find_named_lists(payload, f"payload[{i}]", named_lists)

    text = " | ".join(summaries)

    if named_lists:
        named_summaries = []
        for path, lst in named_lists[:5]:
            sample = json.dumps(lst[0])[:600] if lst else "(empty)"
            named_summaries.append(f"{path} (len={len(lst)}) first item: {sample}")
        text += " || NAMED LISTS: " + " ;; ".join(named_summaries)

    if biggest_list:
        sample_item = json.dumps(biggest_list[0])[:1000]
        text += f" | largest list anywhere (len={len(biggest_list)}) first item: {sample_item}"

    return text


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
    diagnostic = result.diagnostic
    if not diagnostic:
        if result.captured:
            # We captured real JSON but extract_listings' generic
            # price/quantity key-matching found nothing usable in it.
            # Summarize every payload (not just the first - one can look
            # empty, e.g. pagination metadata with "listings": [], while
            # the real data sits in a different captured response).
            diagnostic = (
                f"captured {len(result.captured)} JSON payload(s) but found no "
                f"quantity-aware listing dicts in them; "
                f"{summarize_captured_payloads(result.captured)}"
            )
        elif fallback_price is None:
            diagnostic = "no price found in fallback text"
    return {
        "price_per_ticket": fallback_price,
        "status": "fallback" if fallback_price is not None else "error",
        "confidence": "low",
        "diagnostic": diagnostic,
    }
