import re

from . import common

# Broad on purpose, same rationale as stubhub.py/vividseats.py. Also matches
# api.seatgeek.com directly - the seatgeek.com frontend likely calls its own
# public API client-side, which would let us capture real listing data
# without needing our own SEATGEEK_CLIENT_ID at all.
API_URL_PATTERN = re.compile(r"graphql|listing|inventory|catalog|api\.seatgeek\.com", re.I)


def check_price(url):
    """Returns {price_per_ticket, status, confidence, diagnostic, ...}.

    Scraping fallback for when SEATGEEK_CLIENT_ID isn't set or the API call
    fails - SeatGeek's own site, not the official API.

    status: "ok" (real 2-together price from captured JSON), "fallback"
    (crude text heuristic used instead), "blocked" (bot detection), or
    "error" (unexpected failure).
    """
    return common.check_price(url, API_URL_PATTERN)
