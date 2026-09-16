"""Tracks per-target booked state in a single JSON file, keyed by target
key, so a restarted process (crash, Fly.io redeploy) doesn't double-book a
target that already succeeded, while other targets keep being watched
independently.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

STATE_PATH = os.environ.get("RESY_STATE_PATH", "state.json")


def _load_all():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)


def is_booked(key):
    return _load_all().get(key, {}).get("booked", False)


def get_booking(key):
    return _load_all().get(key, {}).get("booking")


def mark_booked(key, day, time, reservation_id):
    all_state = _load_all()
    booking = {"day": day, "time": time, "reservation_id": reservation_id}
    all_state[key] = {"booked": True, "booking": booking}
    with open(STATE_PATH, "w") as f:
        json.dump(all_state, f, indent=2)
    logger.info("[%s] state written: %s", key, all_state[key])
