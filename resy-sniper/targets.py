"""Loads and validates the list of reservations to snipe from targets.json.

Each target is independent - its own venue, its own natural-language
request (parsed into search criteria once at startup by request_parser),
its own enabled/dry_run override, its own booked-state (state.py). To add,
pause, or remove a target, edit targets.json and redeploy - no code
changes needed for the common case.
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
    party_size_override: Optional[int] = None  # wins over whatever the LLM parses
    enabled: bool = True
    dry_run: Optional[bool] = None  # None = fall back to the global RESY_DRY_RUN


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
