"""What we're trying to book, and the guardrails around booking it.

Every value here is overridable by environment variable so the same code
runs unchanged locally, on Vercel Cron and on Fly.io.
"""

import os
from dataclasses import dataclass, field
from datetime import time

# --- credentials (never hard-code these; see README) -------------------
RESY_API_KEY = os.environ.get("RESY_API_KEY", "")
RESY_AUTH_TOKEN = os.environ.get("RESY_AUTH_TOKEN", "")

# --- politeness / safety knobs ----------------------------------------
# Seconds between outbound Resy calls. Lower = faster snipe, higher = less
# likely to get rate-limited or flagged. 0.5s is roughly what Resy's own
# web client does when you click around.
MIN_REQUEST_INTERVAL = float(os.environ.get("RESY_MIN_REQUEST_INTERVAL", 0.5))

# Booking is irreversible and can incur a cancellation fee. Nothing books
# for real unless this is explicitly set to "1"/"true" - the default is a
# dry run that logs the slot it *would* have taken.
LIVE_BOOKING = os.environ.get("RESY_LIVE_BOOKING", "").lower() in ("1", "true", "yes")


def _env_weekdays(name, default):
    """Parse "5" or "4,5,6" from the environment into weekday ints.

    Mostly a testing affordance: the real target is Saturdays, but when you
    are smoke-testing against a restaurant that has tables free tomorrow you
    want to scan every day without editing code.
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    return tuple(int(part) for part in raw.split(",") if part.strip() != "")


def _env_time(name, default):
    """Parse "HH:MM" from the environment, falling back to `default`."""
    raw = os.environ.get(name)
    if not raw:
        return default
    hour, _, minute = raw.partition(":")
    return time(int(hour), int(minute or 0))


@dataclass
class Target:
    """One restaurant/date pattern being sniped."""

    key: str  # filesystem-safe slug, namespaces this target's state
    name: str
    venue_id: int
    party_size: int

    # Which days of the week to hunt, as Python weekday ints (Mon=0, Sun=6).
    weekdays: tuple

    # How far out to look. Resy venues typically open a rolling window
    # ~30 days ahead, so scanning past that is just wasted requests.
    days_ahead: int = 60

    # Dinner is preferred but the ask was "flexible on exact time", so
    # there are two windows: anything inside `preferred` is taken first,
    # anything inside `acceptable` is taken if nothing better exists.
    preferred_start: time = time(18, 0)
    preferred_end: time = time(21, 0)
    acceptable_start: time = time(17, 0)
    acceptable_end: time = time(22, 0)

    # "A table for 2" - bar/counter stools are a different experience, so
    # they're skipped unless explicitly allowed.
    allow_bar_seating: bool = False
    bar_seating_keywords: tuple = ("bar", "counter", "stool")

    # Hard ceiling on the cancellation fee this bot may commit you to
    # *without asking*, in dollars. The default of 0 means: book free slots
    # outright, and bring anything that costs money to you with the price
    # and the terms so you can decide. Raising it widens what books
    # unattended - do that deliberately, not by accident.
    max_cancellation_fee: float = 0.0

    # Extra addresses to notify on success, beyond ALERT_EMAIL_TO.
    extra_recipients: list = field(default_factory=list)

    def slot_is_bar(self, config_type):
        lowered = (config_type or "").lower()
        return any(word in lowered for word in self.bar_seating_keywords)


TARGETS = [
    Target(
        key="pizza-4ps-brooklyn",
        name="Pizza 4P's Brooklyn (Greenpoint)",
        # Resy's numeric venue id. There is no stable public list of these,
        # so resolve it once with `python cli.py find-venue "Pizza 4P's"`
        # and set RESY_VENUE_ID (or paste the number here).
        venue_id=int(os.environ.get("RESY_VENUE_ID", 0)),
        party_size=int(os.environ.get("RESY_PARTY_SIZE", 2)),
        weekdays=_env_weekdays("RESY_WEEKDAYS", (5,)),  # default Saturday (Mon=0)
        days_ahead=int(os.environ.get("RESY_DAYS_AHEAD", 60)),
        preferred_start=_env_time("RESY_PREFERRED_START", time(18, 0)),
        preferred_end=_env_time("RESY_PREFERRED_END", time(21, 0)),
        acceptable_start=_env_time("RESY_ACCEPTABLE_START", time(17, 0)),
        acceptable_end=_env_time("RESY_ACCEPTABLE_END", time(22, 0)),
        allow_bar_seating=os.environ.get("RESY_ALLOW_BAR", "").lower() in ("1", "true", "yes"),
        max_cancellation_fee=float(os.environ.get("RESY_MAX_CANCELLATION_FEE", 0)),
    ),
]
