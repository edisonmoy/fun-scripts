import os

# The one screening this watches: Paul Thomas Anderson's "Cameron Winter at
# Carnegie Hall", world premiere, Oct 1 2026, 9:15 PM, Alice Tully Hall.
# Tessitura performance id (from filmlinc.org's embedded showtime JSON).
FILM_PAGE_URL = os.environ.get(
    "PTA_FILM_PAGE_URL",
    "https://www.filmlinc.org/nyff2026/films/cameron-winter-at-carnegie/",
)
PERFORMANCE_ID = os.environ.get("PTA_PERFORMANCE_ID", "84536")
PRODUCTION_SEASON_ID = os.environ.get("PTA_PRODUCTION_SEASON_ID", "84535")
PURCHASE_URL = os.environ.get(
    "PTA_PURCHASE_URL",
    f"https://purchase.filmlinc.org/{PRODUCTION_SEASON_ID}/{PERFORMANCE_ID}",
)

# How many tickets to grab once it's available (site max is 2/household).
TICKET_QUANTITY = int(os.environ.get("PTA_TICKET_QUANTITY", 2))

# When true (default), a detected opening only sends an alert - it never
# attempts the real purchase flow. filmlinc.org runs real bot defenses
# (Imperva Incapsula on login, Queue-it gating the buy widget - see
# README) that a headless browser may simply fail against, so this stays
# true until PTA_DRY_RUN=false is set deliberately, same safety posture as
# resy-sniper's RESY_DRY_RUN.
DRY_RUN = os.environ.get("PTA_DRY_RUN", "true").lower() != "false"

# Film at Lincoln Center / Tessitura patron account credentials - required
# for the (best-effort) auto-purchase path. Not needed in dry-run mode.
FLC_EMAIL = os.environ.get("PTA_FLC_EMAIL")
FLC_PASSWORD = os.environ.get("PTA_FLC_PASSWORD")

POLL_INTERVAL_SECONDS = float(os.environ.get("PTA_POLL_INTERVAL_SECONDS", 60))
POLL_JITTER_SECONDS = float(os.environ.get("PTA_POLL_JITTER_SECONDS", 10))
