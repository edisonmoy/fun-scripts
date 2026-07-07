import re

from . import common

# Broad on purpose: the real internal API path wasn't observable while
# building this (see README known limitations). Tighten once a real
# captured URL/payload is seen.
API_URL_PATTERN = re.compile(r"graphql|listing|inventory|catalog", re.I)


def check_price(url):
    """Returns {price_per_ticket, status, confidence, diagnostic, ...}.

    status: "ok" (real 2-together price from captured JSON), "fallback"
    (crude text heuristic used instead), "blocked" (bot detection), or
    "error" (unexpected failure).
    """
    return common.check_price(url, API_URL_PATTERN)
