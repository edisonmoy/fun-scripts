import os

# The show we're watching
EVENT_NAME = "Noah Kahan - The Great Divide Tour"
EVENT_DATE = "2026-07-19"
EVENT_VENUE = "Citi Field, Flushing, NY"

SEATGEEK_EVENT_ID = 18065521
SEATGEEK_PERFORMER_SLUG = "noah-kahan"  # used to pull every tour date for the supply/demand signal

STUBHUB_URL = "https://www.stubhub.com/noah-kahan-flushing-tickets-7-19-2026/event/160467853/"
VIVIDSEATS_URL = "https://www.vividseats.com/noah-kahan-tickets-flushing-citi-field-7-19-2026--concerts-pop/production/6642335"

# Alert thresholds (per ticket). Edit these to taste.
# Current market per the user: ~$650-750/ticket. Both conditions are checked;
# either one firing triggers an email.
PRICE_TARGET_PER_TICKET = float(os.environ.get("PRICE_TARGET_PER_TICKET", 500))
PCT_DROP_THRESHOLD = float(os.environ.get("PCT_DROP_THRESHOLD", 15))  # percent

# Sanity bounds used to filter junk numbers out of scraped page text
# (fees, unrelated $ amounts, parking passes, etc.)
MIN_SANE_TICKET_PRICE = 30
MAX_SANE_TICKET_PRICE = 5000
