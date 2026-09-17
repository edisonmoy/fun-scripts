"""Loads and validates the list of reservations to snipe from targets.json.

Each target is independent - its own venue, its own natural-language
request (parsed into search criteria once at startup by request_parser),
its own enabled/dry_run override. To add, pause, or remove a target, edit
targets.json and redeploy - no code changes needed for the common case.

Booking state (`booking`) lives in this same file rather than local disk,
and github_sync.py is what writes it back once a target books - Fly's
container disk is ephemeral, so anything local would be forgotten on the
next redeploy, and the file already round-trips through the management
webapp anyway.
"""
import json
import os
from dataclasses import dataclass
from typing import Optional

TARGETS_PATH = os.environ.get("RESY_TARGETS_PATH", "targets.json")


@dataclass
class Target:
    key: str  # short, filesystem/log-safe slug; namespaces this target's state
    venue_name: str
    request: str  # free-text description, parsed by request_parser.parse()
    venue_id: Optional[int] = None  # pin once resolved; skips a search call every restart
    enabled: bool = True
    # True = "notify mode" (email on a match, don't book), False = "book
    # mode" (book automatically), None = fall back to the global
    # RESY_DRY_RUN. The dashboard presents this as Notify/Book mode -
    # the field is still named dry_run here since that's the accurate
    # description of what it gates (the /3/book call), not of the
    # notify-mode behavior around it.
    dry_run: Optional[bool] = None
    booking: Optional[dict] = None  # set by github_sync.record_booking() once booked


def load(path=None):
    path = path or TARGETS_PATH
    with open(path) as f:
        raw = json.load(f)

    targets = [Target(**entry) for entry in raw]

    keys = [t.key for t in targets]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise ValueError(f"duplicate target keys in {path}: {sorted(duplicates)}")

    return targets
