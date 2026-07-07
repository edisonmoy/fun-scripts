from . import common


def get_lowest_price_per_ticket(url):
    """Best-effort lowest listed price per ticket on Vivid Seats.

    Same caveats as scrapers/stubhub.py: heuristic price extraction from
    rendered page text, not a guaranteed "2 seats together" price.
    """
    text = common.fetch_rendered_text(url)
    return common.lowest_sane_price(text)
