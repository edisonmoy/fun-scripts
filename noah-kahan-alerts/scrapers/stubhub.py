from . import common


def get_lowest_price_per_ticket(url):
    """Best-effort lowest listed price per ticket on StubHub.

    StubHub runs aggressive bot detection; this is a heuristic (cheapest
    plausible $ amount on the rendered page) rather than a guaranteed "2
    seats together" price, and selectors/approach may need updating once
    run against the live site. See README for known limitations.
    """
    text = common.fetch_rendered_text(url)
    return common.lowest_sane_price(text)
