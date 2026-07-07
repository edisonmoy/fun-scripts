import os
from dataclasses import dataclass

# Global settings shared by every watched event.

# Sanity bounds used to filter junk numbers out of scraped page text
# (fees, unrelated $ amounts, parking passes, etc.)
MIN_SANE_TICKET_PRICE = 30
MAX_SANE_TICKET_PRICE = 5000

# Default percent-drop-from-floor alert threshold, used by any event that
# doesn't set its own. Can be overridden per event below.
DEFAULT_PCT_DROP_THRESHOLD = float(os.environ.get("PCT_DROP_THRESHOLD", 15))

# Consecutive blocked/error scraper runs before we open a GitHub issue.
ESCALATION_THRESHOLD = 3


@dataclass
class WatchedEvent:
    """One show being monitored. Add another instance to WATCHED_EVENTS
    below to track a different concert/artist - nothing else in this
    project is specific to any one show.
    """

    key: str  # short, filesystem-safe slug; namespaces this event's stored data
    name: str
    date: str
    venue: str
    seatgeek_event_id: int
    seatgeek_performer_slug: str  # pulls every tour date for the supply/demand signal
    seatgeek_url: str  # scraping fallback target when SEATGEEK_CLIENT_ID isn't set/working
    stubhub_url: str
    vividseats_url: str
    price_target_per_ticket: float  # flat dollar alert threshold, per ticket
    pct_drop_threshold: float = DEFAULT_PCT_DROP_THRESHOLD


WATCHED_EVENTS = [
    WatchedEvent(
        key="noah-kahan-citi-field-2026-07-19",
        name="Noah Kahan - The Great Divide Tour",
        date="2026-07-19",
        venue="Citi Field, Flushing, NY",
        seatgeek_event_id=18065521,
        seatgeek_performer_slug="noah-kahan",
        seatgeek_url=(
            "https://seatgeek.com/noah-kahan-tickets/flushing-new-york-citi-field-"
            "2026-07-19-6-30-pm/concert/18065521"
        ),
        # quantity=2 filters the listing grid down to pairs of seats sold
        # together - without it the page (and our scraper) defaults to
        # showing single tickets, which is a different, usually much lower,
        # price. Confirmed against the live Vivid Seats page: 1 ticket
        # showed $390 lowest, 2 tickets together showed $599 lowest.
        stubhub_url=(
            "https://www.stubhub.com/noah-kahan-flushing-tickets-7-19-2026/"
            "event/160467853/?quantity=2"
        ),
        vividseats_url=(
            "https://www.vividseats.com/noah-kahan-tickets-flushing-citi-field-"
            "7-19-2026--concerts-pop/production/6642335?quantity=2"
        ),
        price_target_per_ticket=float(os.environ.get("PRICE_TARGET_PER_TICKET", 500)),
    ),
]
