import logging
import random
import re
import time

from playwright.sync_api import sync_playwright

import config

logger = logging.getLogger(__name__)

# Deliberately not overriding user_agent - see concert-ticket-alerts/scrapers/
# common.py for why a mismatched UA is itself a bot-detection signal.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
"""

BLOCK_TEXT_MARKERS = [
    "just a moment",
    "verify you are a human",
    "attention required",
    "unusual traffic",
    "are you a robot",
    "request unsuccessful",
]


class AvailabilityError(Exception):
    """Raised when the page couldn't be loaded or looked bot-blocked -
    distinct from "loaded fine, performance just isn't in the data" so
    main.py can tell a real signal from a fetch failure.
    """


def extract_showtime(html, performance_id):
    """Pull the one showtime dict matching `performance_id` out of the
    embedded `associatedShowtimes` JSON on filmlinc.org's film page.

    That JSON is server-rendered straight into the page as part of a React
    Server Components payload rather than served from a separately
    fetchable endpoint, and each showtime entry nests further structures
    (presaleSchedule.saleDates[...]) after the fields we care about - so
    rather than parse a full JSON object (which would require correctly
    matching nested braces), this greps a fixed-size window right after
    the matching "id" key for the handful of flat fields that appear
    before that nesting starts. Schema-agnostic-ish and tolerant of key
    reordering, same tradeoff concert-ticket-alerts' scraper makes for
    similarly-shaped SSR JSON blobs.
    """
    marker = f'"id":"{performance_id}"'
    idx = html.find(marker)
    if idx == -1:
        return None
    window = html[idx : idx + 1500]

    def field(pattern, cast=str):
        m = re.search(pattern, window)
        return cast(m.group(1)) if m else None

    available = field(r'"available":(true|false)', lambda v: v == "true")
    status = field(r'"status":"([^"]*)"')
    date = field(r'"date":"([^"]*)"')
    time_str = field(r'"time":"([^"]*)"')
    venue = field(r'"venue":"([^"]*)"')
    tickets_url = field(r'"ticketsUrl":"([^"]*)"')

    if available is None:
        # Found the id but not the fields we expect right after it - the
        # page's data shape changed. Surface this loudly rather than
        # silently reporting "not available".
        raise AvailabilityError(
            f"found performance {performance_id} but couldn't parse its fields; "
            f"window: {window[:300]!r}"
        )

    return {
        "performance_id": performance_id,
        "available": available,
        "status": status,
        "date": date,
        "time": time_str,
        "venue": venue,
        "tickets_url": tickets_url,
    }


def _launch_browser(p):
    """Prefer a real installed Chrome binary over bundled Chromium - see
    concert-ticket-alerts/scrapers/common.py for the rationale (TLS/JA3
    fingerprint, Client Hints). Falls back to bundled Chromium when Chrome
    isn't installed (e.g. local dev).
    """
    launch_args = {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]}
    try:
        return p.chromium.launch(channel="chrome", **launch_args)
    except Exception:
        logger.info("real Chrome channel unavailable, falling back to bundled Chromium")
        return p.chromium.launch(**launch_args)


def fetch_availability(retries=3):
    """Load the public NYFF film page and return the parsed showtime dict
    for config.PERFORMANCE_ID. Raises AvailabilityError on a blocked or
    failed fetch after all retries - callers should treat that as "unknown,
    try again next round", not "not available".
    """
    last_error = None
    for attempt in range(1, retries + 1):
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
                # Not checking the navigation response's status code here:
                # filmlinc.org fronts pages with a Cloudflare JS challenge
                # that issues an initial 403 and then auto-resolves and
                # reloads client-side (confirmed live - the final page.content()
                # is the real rendered page even though page.goto()'s response
                # object reports the challenge's 403). Only the final
                # rendered text is a reliable signal of an actual block.
                page.goto(config.FILM_PAGE_URL, timeout=30000, wait_until="domcontentloaded")
                # The Cloudflare challenge page never reaches "networkidle"
                # (confirmed live - it keeps some connection alive, so that
                # wait just burns its full timeout every time) and its solve
                # time varies (seen anywhere from ~6s to never resolving at
                # all under repeated automated hits - see README). Poll the
                # title instead of trusting a single fixed wait.
                deadline = time.time() + 25
                while page.title() == "Just a moment..." and time.time() < deadline:
                    page.wait_for_timeout(1000)
                html = page.content()
                browser.close()

            lowered = html.lower()
            if any(m in lowered for m in BLOCK_TEXT_MARKERS):
                raise AvailabilityError("blocked (challenge page in final rendered content)")

            showtime = extract_showtime(html, config.PERFORMANCE_ID)
            if showtime is None:
                raise AvailabilityError(
                    f"performance {config.PERFORMANCE_ID} not found on page at all"
                )
            return showtime
        except AvailabilityError as exc:
            last_error = exc
        except Exception as exc:
            last_error = AvailabilityError(f"{type(exc).__name__}: {exc}")

        logger.warning("attempt %d/%d failed: %s", attempt, retries, last_error)
        if attempt < retries:
            time.sleep(2**attempt + random.uniform(0, 1))

    raise last_error
